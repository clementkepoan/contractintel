# Current RAG Architecture

This document describes the **current implemented RAG system** after the reset. It reflects the code that is active now, not the later experimental refactors that were discussed previously.

Primary files:
- `backend/pipeline/indexer.py`
- `backend/pipeline/qdrant_store.py`
- `backend/pipeline/langchain_query.py`
- `backend/pipeline/embeddings.py`
- `backend/api/query.py`
- `backend/pipeline/service.py`
- `backend/config.py`

## 1. High-level flow

End-to-end query flow:

1. A contract is ingested and extracted into raw JSON under `data/extracted/{contract_id}.json`.
2. `write_chunk_index()` in `backend/pipeline/indexer.py` builds retrieval chunks from that extracted payload.
3. The chunk index is written to `data/indexes/{contract_id}_chunks.json`.
4. If the embedding model is available, chunk embeddings are generated and stored:
   - locally in the JSON index
   - and in Qdrant if Qdrant is reachable
5. User sends a query to `POST /api/query`.
6. `answer_with_langchain()` in `backend/pipeline/langchain_query.py`:
   - checks local LLM availability
   - classifies query intent
   - expands the query with predefined bilingual legal terms
   - retrieves candidates per contract using `hybrid_search_chunks()`
   - removes `wiki` and `validation_risk` candidates
   - reweights candidates by source type and intent
   - selects final evidence with `select_diverse_citations()`
   - injects fixed structured contract context into the prompt
   - prompts Ollama through `ChatOllama`
7. The answer and citations are stored in chat/query history.

## 2. Source data used by the RAG layer

The current retrieval stack uses three data classes.

### 2.1 Raw extracted blocks
From extracted JSON `extracted["blocks"]`.

Typical block fields:
- `block_id`
- `text`
- `para_start`
- `para_end`
- `page_estimate`

These feed `clause` and `subclause` chunk construction.

### 2.2 Structured extracted fields
These are turned into synthetic retrieval chunks.

Currently used fields:
- `contract_name`
- `contract_key`
- `currency`
- `total_amount`
- `payment_type`
- `milestones`
- `retention`
- `version_conflicts`

### 2.3 Database-backed metadata injected into prompt
Used by `build_structured_context()` and injected regardless of retrieval ranking.

Current DB-backed fields:
- `Contract.contract_name`
- `Contract.source_file`
- `Contract.total_amount`
- `Contract.currency`
- `Contract.contract_type`
- `ValidationWarning` rows

Important distinction:
- validation warnings are injected into prompt context for some queries
- but `validation_risk` retrieval chunks are currently filtered out before final selection

## 3. Chunking strategy

Chunking lives in `backend/pipeline/indexer.py`.

### 3.1 Text normalization and tokenization

Functions:
- `normalize_space(text)`
- `tokenize(text)`

Behavior:
- collapses whitespace
- lowercases before tokenization
- token regex is:
  - `[a-z0-9_]+`
  - `Chinese spans of 1-4 chars`
  - `%` / `％`

Practical effect:
- English words remain searchable
- Chinese is tokenized into short spans
- percent symbols are preserved

### 3.2 Chunk size and overlap

Configured in `backend/config.py`:
- `CHUNK_SIZE = 800`
- `CHUNK_OVERLAP = 100`

Function:
- `split_text_with_overlap(text, target_size, overlap)`

Behavior:
- if text length <= 800 chars, keep as one chunk
- otherwise split into sliding windows
- overlap applies only when splitting an oversized chunk
- there is no explicit inter-clause overlap strategy

### 3.3 Clause grouping

Function:
- `build_clause_groups(blocks)`

Clause boundary rule:
- start a new clause when block text matches `^第[一二三四五六七八九十百千\d]+條`

Each clause group stores:
- `label`
- `blocks`

If a file begins before the first detected clause header, those leading blocks are grouped into an unlabeled clause group.

### 3.4 Clause chunks

Function:
- `build_clause_chunks(extracted)`

Per clause group:
- concatenate all block texts in the group with newlines
- split with `split_text_with_overlap()` if needed
- each part becomes a `clause` chunk

Clause chunk metadata:
- `chunk_id`: `clause::{group_index}` or `clause::{group_index}__partNN`
- `chunk_type`: `clause`
- `clause_label`
- `para_start`
- `para_end`
- `page_estimate`
- `source_label`
- `block_ids`

### 3.5 Subclause chunks

Also built in `build_clause_chunks(extracted)`.

Current logic is shallow.

A subclause is created when a member block matches either:
- `MILESTONE_HEADER_RE`
- `SUBCLAUSE_SIGNAL_RE`

Then:
- the triggering block is included
- optionally the immediately following block is appended
- but only if the next block is not another clause header and not another milestone header

This means the current subclause strategy is usually:
- one triggering block
- plus maybe one following block

This is the main current chunking weakness for long numbered clause lists.

`SUBCLAUSE_SIGNAL_RE` includes terms like:
- `給付`
- `付款`
- `請款`
- `驗收`
- `違約`
- `違約金`
- `扣罰`
- `保固`
- `保證金`
- `固定總價`
- `追加工程款`

`MILESTONE_HEADER_RE` includes patterns such as:
- `第X期`
- `里程碑X`
- `工程節點X`
- `階段X`

Subclause chunk metadata:
- `chunk_id`: `subclause::{group_index}:{para_start}`
- `chunk_type`: `subclause`
- `clause_label`
- `para_start`
- `para_end`
- `page_estimate`
- `source_label`
- `block_ids`

### 3.6 Structured chunks

Function:
- `build_structured_chunks(extracted, clause_groups)`

Current structured chunk kinds actively built:

#### 3.6.1 `contract_summary`
One per contract.

Includes:
- contract name
- total amount
- currency
- payment type
- milestone count

#### 3.6.2 `milestone_summary`
One per milestone.

Includes:
- milestone name
- amount
- percentage
- payment condition
- acceptance criteria
- work items

Metadata includes milestone citation block IDs when present.

#### 3.6.3 `retention_summary`
Only if retention has amount or release condition.

Includes:
- retention amount
- retention percentage
- release condition
- release-after-months

#### 3.6.4 `version_conflict_summary`
One per version conflict.

Includes:
- changed field
- old value
- new value

#### 3.6.5 `clause_action_summary`
Built for clause groups whose merged text matches `ACTION_SIGNAL_RE`.

`ACTION_SIGNAL_RE` includes terms like:
- `得`
- `暫停付款`
- `違約金`
- `扣罰`
- `終止`
- `解除`
- `另覓廠商`
- `書面通知`
- `不補償`
- `費用由乙方負擔`

The summary text is produced by `summarize_action_sentences(text)`:
- split on `。`, `；`, and newline
- keep units containing action signals
- join up to 3 selected units
- fallback to first 300 chars if no signal unit is found

### 3.7 Wiki chunk code

Function exists:
- `build_wiki_chunks(extracted)`

It can:
- read contract/source/milestone markdown pages
- strip frontmatter
- split by `##` headings
- filter out low-signal headings
- build `wiki` chunks

But in the current code path, this function is **dead for indexing**.

Important current fact:
- `build_chunks()` does **not** call `build_wiki_chunks()`
- therefore wiki pages are **not** included in the active index
- however query code still knows wiki page paths for UI linking via `resolve_contract_wiki_paths()`

## 4. What is stored in the local chunk index

Written by:
- `write_chunk_index(contract_id, extracted)`

Target file:
- `data/indexes/{contract_id}_chunks.json`

Stored fields:
- `contract_id`
- `chunks`
- `tokenized_chunks`
- `embedding_model`
- optionally `embeddings`
- optionally `bm25_idf`

Each chunk record currently contains:
- `chunk_id`
- `text`
- `para_start`
- `para_end`
- `page_estimate`
- `chunk_type`
- `clause_label`
- `structured_kind`
- `wiki_source_path`
- `source_label`
- `block_ids`

Notably absent in current code:
- `milestone_id`
- `milestone_key`
- `milestone_name`

So milestone-aware retrieval is still indirect and text-based.

## 5. Qdrant storage

Implemented in `backend/pipeline/qdrant_store.py`.

### 5.1 Collection
Configured in `backend/config.py`:
- collection name: `contract_chunks`

Qdrant vector size is created dynamically from the embedding vector length.
Distance metric:
- cosine

### 5.2 Payload stored per chunk
Current Qdrant payload fields:
- `contract_id`
- `chunk_id`
- `para_start`
- `para_end`
- `page_estimate`
- `chunk_type`
- `clause_label`
- `structured_kind`
- `wiki_source_path`
- `source_label`
- `block_ids`

Missing from current payload:
- milestone identifiers
- explicit clause family tags beyond `clause_label`

### 5.3 Reindex behavior
`upsert_contract_chunks()` deletes existing Qdrant points for the contract before inserting the new set.

## 6. Embedding model

Implemented in `backend/pipeline/embeddings.py`.

Current default model in `backend/config.py`:
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

Properties of the current implementation:
- runs offline-only with `HF_HUB_OFFLINE=1`
- local snapshot must already exist
- `embed_texts()` normalizes embeddings
- same embedding model is used for indexing and query vectors

If the model is unavailable locally:
- embeddings are disabled
- hybrid retrieval falls back to BM25-only

## 7. Retrieval pipeline

Main entry point:
- `hybrid_search_chunks(contract_id, query, top_k)`

### 7.1 BM25 retrieval
Current implementation uses **two different BM25-related paths**.

At index build time:
- `BM25Okapi` is instantiated over `tokenized_chunks`
- only `idf` is saved into the JSON payload

At retrieval time:
- it does **not** use the saved `BM25Okapi` scores directly
- instead it rebuilds a `BM25Retriever` from LangChain `Document` objects
- then invokes it with `preprocess_func=tokenize`

Important consequence:
- returned `bm25_score` is **not** a raw BM25 float score
- it is derived from rank position only:
  - `1.0 / rank`

So current BM25 scoring is rank-based rather than true score-based.

### 7.2 Vector retrieval
Two paths exist:

#### Qdrant path
Function:
- `qdrant_vector_search(contract_id, query, top_k)`

Used when:
- embedding model is ready
- Qdrant is reachable

#### Local vector path
Function:
- `vector_search(index_payload, query, top_k)`

Used when:
- embedding model is ready
- Qdrant did not produce vector results

Method:
- embed query locally
- cosine similarity against stored local embeddings

### 7.3 Reciprocal Rank Fusion
Function:
- `reciprocal_rank_fusion(rankings, k=60)`

Inputs:
- BM25 ranking
- vector ranking if available

Output:
- fused score per `chunk_id`

Current retrieval score stored in results:
- `retrieval_score = fused RRF score`

Current auxiliary scores stored in each result:
- `bm25_score`
- `vector_score`

But note:
- `bm25_score` is rank-derived, not true BM25
- vector score is a real similarity score when vector retrieval is active

### 7.4 Retrieval mode labels
`retrieval_method` in results is set to:
- `hybrid_qdrant`
- `hybrid_local`
- `bm25`

`retrieval_mode()` in `langchain_query.py` returns for answer metadata:
- `hybrid_qdrant`
- `hybrid_local`
- `bm25_only`

## 8. Query normalization and intent handling

Implemented in `backend/pipeline/langchain_query.py`.

### 8.1 Heuristic intent classification
Function:
- `classify_query_intents(query)`

Current supported intents:
- `action`
- `progress_delay`
- `payment`
- `risk`

This is regex/keyword based only.
There is no learned classifier in the current code.

Patterns include:
- action: phrases like `可以採取哪些行動`, `甲方可以`
- progress delay: `進度`, `落後`, `逾期`, `延誤`
- payment: `付款`, `請款`, `工程款`, `期款`, `給付`, or English `payment`
- risk: `風險`, `違約`, `罰款`, `扣罰`, or English `risk` / `penalty`

This is still brittle for paraphrased natural phrasing.

### 8.2 Query expansion
Function:
- `expand_query(query, intents)`

Current dictionary expansions include English triggers like:
- `risk`
- `payment`
- `milestone`
- `penalty`
- `retention`
- `warranty`
- `delay`
- `change`

Additional hardcoded expansions are appended for:
- `action`
- `progress_delay`

Expansion strategy:
- preserve original query
- append Chinese legal terms as extra lines

### 8.3 Output language detection
Function:
- `detect_output_language(query)`

Rule:
- compare Chinese character count vs ASCII letter count
- output language is either:
  - `繁體中文`
  - `English`

This controls answer style instructions, not retrieval.

## 9. Evidence weighting and final selection

Implemented in `backend/pipeline/langchain_query.py`.

### 9.1 Pre-selection filtering
In `answer_with_langchain()`, before final selection:
- all `wiki` chunks are dropped
- all `validation_risk` structured chunks are dropped

So even if such chunks were retrieved, they are removed before the final answer set.

Current result:
- active evidence is document-first and structured-summary-limited
- validation warnings do not participate in final retrieval evidence
- wiki chunks do not participate in final retrieval evidence

### 9.2 Source weighting
Function:
- `source_weight(item, intents)`

Current weighting behavior:
- `clause`: positive boost
- `subclause`: positive boost
- `structured::clause_action_summary`: stronger positive boost
- `contract_summary`: slight penalty
- `milestone_summary`: slight penalty for action questions
- `retention_summary`: slight penalty for action questions
- `validation_risk`: penalized, especially for action questions
- `wiki`: strong penalty

Additional boosts apply when:
- action-related terms appear in the chunk text
- progress-delay terms appear in the chunk text

### 9.3 Expanded ranking
Function:
- `expand_related_action_candidates(citations, intents)`

This does not add new neighbors from the document graph.
It simply adds source-weight bonuses to `retrieval_score`.

### 9.4 Final citation selection
Function:
- `select_diverse_citations(citations, top_k, intents)`

Current policy:
- clause/subclause evidence is preferred first
- structured chunks are added next, with `clause_action_summary` preferred among structured
- wiki is only considered if there is no clause-like evidence
- final fallback loop fills remaining slots by descending adjusted score

Because `wiki` and `validation_risk` are already filtered out earlier, the practical final evidence set is usually:
- clause chunks
- subclause chunks
- selected structured chunks, mostly action summaries and milestone/contract summaries

## 10. Structured context injection

Implemented by:
- `build_structured_context(session, contract_ids, intents)`

This is always injected into the prompt before retrieved evidence.

Current fields injected:
- contract name
- source file
- total amount
- currency
- payment type
- milestone count
- retention summary if present
- validation warnings only when query is **not** `action` and **not** `progress_delay`

So for action/progress-delay queries, validation warnings are deliberately suppressed from structured context.

## 11. Prompt construction and answer generation

Implemented in `answer_with_langchain()`.

### 11.1 LLM requirement
If `llm_available()` is false:
- query endpoint fails with `503`
- there is no answer fallback path anymore

### 11.2 Prompt shape
System prompt is in Traditional Chinese and tells the model to:
- answer only from provided evidence
- prioritize original clause evidence
- treat history only as pronoun/reference context
- answer like a contract analyst, not a generic summarizer
- check specific engineering-contract clause families
- match final answer language to user language

Human prompt sections are:
- `【合約結構化資料】`
- `【檢索證據】`
- `【回答要求】`
- `【問題】`

### 11.3 Answer requirements
`build_answer_instructions(intents, output_language)` adds intent-specific instructions.

Current special guidance exists for:
- action/progress-delay questions
- payment questions
- risk questions

These instructions try to force multi-clause aggregation, but success still depends on retrieved evidence quality and model capability.

### 11.4 Model runtime
Answer generation uses:
- `ChatOllama`
- `model = settings.local_model_name`
- `base_url = settings.local_model_base_url`
- `temperature = 0`
- `num_ctx = settings.local_model_num_ctx`

Current default model in config:
- `qwen3:8b`

## 12. API behavior

Implemented in `backend/api/query.py`.

### 12.1 Query endpoint
`POST /api/query`

Payload:
- `query`
- `top_k` default `12`
- optional `contract_id`
- optional `chat_session_id`
- optional `persist_to_wiki`

Behavior:
- requires local LLM ready
- if `contract_id` absent, searches across all active contracts returned by `get_all_contracts(session)`
- multi-contract search is done by looping contracts in Python, not by one global Qdrant query

### 12.2 Session endpoints
Current endpoints:
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{id}/messages`
- `GET /api/chat/sessions/{id}/latest-query`
- `GET /api/chat/sessions/{id}/turns`

Per-turn query persistence is backed by `FiledQuery` rows linked to `human_message_id` and `ai_message_id`.

## 13. Persistence and wiki linkage

### 13.1 Query persistence
Every answered query stores:
- question
- answer
- citations
- retrieval mode
- answer method
- chat session linkage

If `persist_to_wiki` is enabled:
- `append_query_note()` writes a wiki query note
- and persists query metadata there

If disabled:
- `record_query_result()` stores it only in DB

### 13.2 Wiki linkage in retrieval results
Even though wiki chunks are not active retrieval evidence, `answer_with_langchain()` still attaches wiki page paths to hits when possible using:
- `resolve_contract_wiki_paths(session, contract_id)`

This is for frontend navigation such as:
- source page link
- project page link

It is not evidence retrieval.

## 14. Current strengths

1. Document-first retrieval bias is clear.
2. Clause-level chunks are much better than raw paragraph-only indexing.
3. Structured summaries help with milestone/payment/risk phrasing.
4. Query expansion helps English contract terms hit Chinese corpora.
5. Prompt is contract-domain-aware rather than generic.
6. No query answer is produced when the local LLM is unavailable.
7. Session history and per-turn evidence persistence are implemented.

## 15. Current limitations

1. **Subclause chunking is still shallow**
- one trigger block plus maybe one following block
- poor fit for long numbered item sequences

2. **Intent classification is brittle**
- regex-only
- misses paraphrased intent

3. **BM25 scoring is rank-derived, not true score-based**
- `bm25_score` is currently `1/rank`
- not the underlying BM25 float score

4. **No milestone identity in retrieval metadata**
- no `milestone_id` / `milestone_key` in chunk payloads
- milestone-scoped retrieval remains indirect

5. **Dead wiki chunk code remains in indexer**
- `build_wiki_chunks()` exists but is not used by `build_chunks()`

6. **Validation warning retrieval is disabled before final selection**
- `validation_risk` chunks can exist conceptually but are filtered out
- warnings are also suppressed from structured context for action/progress queries

7. **No reranker beyond source-weighted RRF**
- no cross-encoder rerank
- no explicit clause-neighbor expansion

8. **Multi-contract search is contract-by-contract looped retrieval**
- not one unified global retrieval pass

## 16. Runtime defaults relevant to RAG

From `backend/config.py`:
- local model: `qwen3:8b`
- local model base URL: `http://localhost:11434`
- embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- qdrant URL: `http://qdrant:6333`
- chunk size: `800`
- chunk overlap: `100`
- local LLM context window: `8192`

## 17. Practical summary

The current RAG system is a **hybrid clause-level contract retriever** with:
- clause chunks
- shallow subclause chunks
- selected structured summary chunks
- BM25 + vector fusion
- source-type reweighting
- structured context injection
- Ollama-based answer generation

It is no longer raw paragraph-only retrieval, but it is also not yet the more advanced architecture that was discussed later.

The biggest current retrieval gaps are:
- shallow subclause segmentation
- regex-only intent handling
- rank-derived BM25 scoring
- lack of milestone identifiers in chunk metadata
- dead wiki indexing code still present but inactive
- validation warnings excluded from final retrieval evidence
