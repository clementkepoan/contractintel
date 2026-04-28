# Current RAG Architecture

This document describes the **current implemented RAG system** in this repository. It is based on the active code in:

- `backend/pipeline/indexer.py`
- `backend/pipeline/qdrant_store.py`
- `backend/pipeline/langchain_query.py`
- `backend/api/query.py`
- `backend/config.py`

It reflects the implementation as it exists now, including places where older capabilities still exist in code but are not part of the active indexing or retrieval path.

## 1. High-Level Flow

The query pipeline is:

1. Contract is ingested into extracted JSON with `blocks` and structured extracted fields.
2. `write_chunk_index()` builds retrieval chunks from that extracted payload.
3. Chunks are written to:
   - local JSON index in `data/indexes/{contract_id}_chunks.json`
   - Qdrant, if embeddings and Qdrant are both available
4. User sends a query to `POST /api/query`.
5. Query is intent-classified and query-expanded.
6. For each target contract, `hybrid_search_chunks()` runs:
   - BM25 retrieval
   - vector retrieval from Qdrant if available, else local embeddings if available
   - reciprocal-rank fusion (RRF)
7. Retrieved candidates are reweighted by query intent and source type.
8. A final evidence set is selected by `select_diverse_citations()`.
9. A fixed structured context block is built from DB + raw extraction.
10. The LLM is prompted in Traditional Chinese system framing, with final answer language controlled by the user query language.
11. The answer, citations, and session linkage are persisted to chat/query history.

## 2. Data Sources Used by RAG

The current RAG system uses three classes of information:

### 2.1 Raw extracted document blocks
These come from the extracted JSON payload under `extracted["blocks"]`.

Each block typically carries:
- `block_id`
- `text`
- `para_start`
- `para_end`
- `page_estimate`

These are the basis for `clause` and `subclause` chunks.

### 2.2 Structured extracted payload fields
These come from the extracted JSON payload and are converted into synthetic retrieval chunks.

Used fields include:
- `contract_name`
- `contract_key`
- `currency`
- `total_amount`
- `payment_type`
- `milestones`
- `retention`
- `version_conflicts`

### 2.3 Database-backed contract metadata
These are injected directly into the prompt via `build_structured_context()` and are not dependent on retrieval ranking.

Used DB fields include:
- `Contract.contract_name`
- `Contract.source_file`
- `Contract.total_amount`
- `Contract.currency`
- `Contract.contract_type`
- `ValidationWarning` rows

## 3. Chunking Strategy

Chunking is implemented in `backend/pipeline/indexer.py`.

### 3.1 Text normalization and tokenization
Functions:
- `normalize_space(text)`
- `tokenize(text)`

Behavior:
- whitespace is collapsed to single spaces
- text is lowercased before tokenization
- tokenizer regex:
  - `[a-z0-9_]+`
  - `[一-鿿]{1,4}`
  - `%` / `％`

Practical effect:
- English tokens are retained
- Chinese is tokenized into short 1-4 char spans
- percentages remain searchable

### 3.2 Chunk size and overlap
Configured in `backend/config.py`:
- `chunk_size = 800`
- `chunk_overlap = 100`

Function:
- `split_text_with_overlap(text, target_size, overlap)`

Behavior:
- if normalized text length is <= 800 chars, keep as one chunk
- otherwise split into sliding windows
- effective step is `target_size - overlap`
- overlap applies only when a single chunk must be split due to size

### 3.3 Clause grouping
Function:
- `build_clause_groups(blocks)`

Clause boundary rule:
- a new clause begins when block text matches `^第[一二三四五六七八九十百千\d]+條`

Each clause group stores:
- `label`: clause header text if present
- `blocks`: list of blocks belonging to that clause until the next clause header

If the file starts before a detected clause header, those leading blocks are grouped into an unlabeled clause group.

### 3.4 Clause chunks
Function:
- `build_clause_chunks(extracted)`

For each clause group:
- all block texts in the group are concatenated with newlines
- the full clause text is split using `split_text_with_overlap()` if needed
- each resulting part becomes a `clause` chunk

Clause chunk metadata:
- `chunk_id`: `clause::{group_index}` or `clause::{group_index}__partNN`
- `chunk_type`: `clause`
- `clause_label`: clause header text or fallback to first block prefix
- `para_start`: first block paragraph
- `para_end`: last block paragraph
- `page_estimate`: first block page estimate
- `block_ids`: all block IDs in the clause group

### 3.5 Subclause chunks
Also built in `build_clause_chunks(extracted)`.

Current logic:
- start from member blocks after the clause header (if header exists)
- iterate block-by-block
- create a `subclause` chunk when a block matches either:
  - `MILESTONE_HEADER_RE`
  - `SUBCLAUSE_SIGNAL_RE`
- if the following block is not a clause header and not another milestone header, it is appended to the same subclause chunk

This means current subclause construction is still relatively shallow:
- one triggering block
- optionally one following block

It is better than raw paragraph-only indexing, but it does **not** yet fully group long numbered clause item sequences into semantically complete subunits.

Subclause signal regex:
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

Milestone header regex captures:
- `第X期`
- `里程碑X`
- `工程節點X`
- `階段X`

Subclause chunk metadata:
- `chunk_id`: `subclause::{group_index}:{para_start}`
- `chunk_type`: `subclause`
- `clause_label`: parent clause label
- `para_start`, `para_end`, `page_estimate`
- `block_ids`: one or two block IDs typically

### 3.6 Structured chunks
Function:
- `build_structured_chunks(extracted, clause_groups)`

These are synthetic chunks created from extracted structured data.

Current structured chunk kinds actively produced:

#### 3.6.1 `contract_summary`
One chunk per contract.

Text includes:
- contract name
- total amount
- currency
- payment type
- milestone count

#### 3.6.2 `milestone_summary`
One chunk per milestone.

Text includes:
- milestone name
- amount
- percentage
- payment condition
- acceptance criteria
- work items

Metadata also carries block IDs from the milestone citations.

#### 3.6.3 `retention_summary`
Only emitted if retention has amount or release condition.

Text includes:
- retention amount
- retention percentage
- release condition
- release-after-months

#### 3.6.4 `version_conflict_summary`
One chunk per version conflict.

Text includes:
- field changed
- old value
- new value

#### 3.6.5 `clause_action_summary`
Generated for clause groups whose merged text matches `ACTION_SIGNAL_RE`.

Action signal regex includes:
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

Text is generated by `summarize_action_sentences(text)`:
- split on `。`, `；`, newline
- keep units containing action signals
- join up to 3 chosen units
- fallback to first 300 chars if no unit is selected

### 3.7 Wiki chunks
Function exists:
- `build_wiki_chunks(extracted)`

It can:
- load wiki markdown from contract/source/milestone pages
- strip frontmatter
- split by `##` heading
- filter low-signal headings
- emit `wiki` chunks

However:
- `build_chunks(extracted)` currently does **not** call `build_wiki_chunks()`
- so wiki chunks are implemented but **not active** in the current indexing pipeline

### 3.8 Active chunk types in the current index
`build_chunks(extracted)` currently returns:
- `clause`
- `subclause`
- `structured`

It does **not** currently include `wiki` chunks in the active index build.

## 4. Chunk Metadata Stored Per Chunk

Chunk objects are created by `chunk_record(...)`.

Current stored fields:
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

Notes:
- `chunk_id` is the stable retrieval identifier within a contract index
- `block_ids` preserve source traceability to raw extracted blocks
- `wiki_source_path` is present in the schema but usually empty in current active indexing because wiki chunks are not built
- there is **no explicit milestone_id** stored in the Qdrant payload for chunk ownership

## 5. Local Index Storage

Function:
- `write_chunk_index(contract_id, extracted)`

Each contract gets a local JSON index file:
- `data/indexes/{contract_id}_chunks.json`

Stored payload fields:
- `contract_id`
- `chunks`
- `tokenized_chunks`
- `embedding_model` if embeddings are ready
- `bm25_idf` if BM25 object was built
- `embeddings` if embedding model is available

This local file supports:
- BM25 retrieval
- local vector retrieval fallback when Qdrant is unavailable but embeddings exist

## 6. Embeddings and Vector Store

### 6.1 Embedding model
Configured in `backend/config.py`:
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

Properties from implementation context:
- multilingual sentence-transformer model
- usually 384-dimensional
- local-files-only loading is enforced in Qdrant integration

### 6.2 Qdrant collection
Configured in `backend/config.py`:
- collection name: `contract_chunks`
- URL: `http://qdrant:6333`

### 6.3 Qdrant collection creation
Function:
- `ensure_collection(vector_size)` in `backend/pipeline/qdrant_store.py`

Behavior:
- create collection if missing
- vector size is inferred from embedding length
- distance metric: cosine

### 6.4 Qdrant payload metadata
Function:
- `upsert_contract_chunks(contract_id, chunks, embeddings)`

For each chunk, Qdrant metadata stores:
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

### 6.5 Upsert behavior
Before inserting contract chunks, the code deletes existing Qdrant points for that `contract_id`.

This prevents stale vectors from older chunking strategies from remaining in the collection.

### 6.6 Point IDs
Point IDs are deterministic UUIDv5 values built from:
- `contract_id`
- `chunk_id`

Function:
- `point_id_for_chunk(contract_id, chunk_id)`

## 7. Retrieval Stack

Retrieval entry points are in `backend/pipeline/indexer.py`.

### 7.1 BM25 retrieval
Function:
- `hybrid_search_chunks(contract_id, query, top_k=5)`

Behavior:
- load local chunk index JSON
- create `Document` objects from chunk texts
- instantiate `BM25Retriever.from_documents(..., preprocess_func=tokenize, k=top_k)`
- retrieve BM25 hits

Returned BM25 metadata per hit:
- `chunk_id`
- `text_snippet` = first 300 chars
- `para_start`
- `para_end`
- `page_estimate`
- `chunk_type`
- `clause_label`
- `structured_kind`
- `wiki_source_path`
- `source_label`
- `block_ids`
- `retrieval_score = 0.0`
- `retrieval_method = "bm25"`

Important limitation:
- BM25Retriever does not expose raw BM25 score here, so all BM25 hits are marked with `retrieval_score = 0.0`
- ranking still comes from returned order and later reciprocal rank fusion

### 7.2 Local vector retrieval
Function:
- `vector_search(index_payload, query, top_k)`

Behavior:
- if local embeddings exist in the JSON index and embedding model is available:
  - embed the query with `embed_texts([query])[0]`
  - compute cosine similarity against stored chunk vectors
  - return top-k `(chunk_id, score)` pairs

### 7.3 Qdrant vector retrieval
Function:
- `qdrant_vector_search(contract_id, query, top_k)`

Behavior:
- if embeddings and Qdrant are available:
  - call `search_contract_chunks(contract_id, query, top_k)`
  - return `(chunk_id, retrieval_score)` pairs

Qdrant search supports optional contract scoping via a `contract_id` filter.

### 7.4 Hybrid fusion
Function:
- `reciprocal_rank_fusion(rankings, k=60)`

Behavior:
- combine BM25 ranking and vector ranking using RRF
- for each ranked list, add `1 / (k + position)` to each chunk
- final chunk ranking is sorted by fused score descending

### 7.5 Final retrieval result shape
`hybrid_search_chunks(...)` returns the final top-k hits with metadata from the local chunk index, plus:
- `retrieval_score`: fused score if present
- `retrieval_method`: `hybrid_qdrant`, `hybrid_local`, or `bm25_only`

### 7.6 Retrieval mode detection
Function:
- `retrieval_mode()` in `backend/pipeline/langchain_query.py`

Returns:
- `hybrid_qdrant` if embeddings and Qdrant are ready
- `hybrid_local` if embeddings are ready but Qdrant is not
- `bm25_only` otherwise

## 8. Query Normalization and Intent Classification

Implemented in `backend/pipeline/langchain_query.py`.

### 8.1 Query intent classification
Function:
- `classify_query_intents(query)`

Current possible intent labels:
- `action`
- `progress_delay`
- `payment`
- `risk`

Detection logic:
- `action` if query matches patterns like:
  - `可以採取哪些行動`
  - `甲方可以`
  - `乙方可以`
  - `得否`
- `progress_delay` if query contains:
  - `進度`
  - `落後`
  - `逾期`
  - `延誤`
- `payment` if query contains Chinese payment terms or the English word `payment`
- `risk` if query contains risk terms or English `risk` / `penalty`

### 8.2 Query expansion
Function:
- `expand_query(query, intents)`

Current English keyword expansions:
- `risk` -> `風險 違約 違約金 扣罰 賠償 逾期 固定總價 不得追加`
- `payment` -> `付款 給付 工程款 請款 期款`
- `milestone` -> `里程碑 期款 工程節點 階段 驗收`
- `penalty` -> `違約金 扣罰 罰則 逾期`
- `retention` -> `保留款 保固保證金 履約保證金 保固期`
- `warranty` -> `保固 保證金 缺失 修繕`
- `delay` -> `逾期 展延 工程進度落後 扣罰`
- `change` -> `變更 追加工程款 固定總價 不得追加`

Intent-driven appended term sets:
- if `action` intent:
  - `得 暫停付款 違約金 扣罰 終止 解除 另覓廠商 書面通知 不補償 費用由乙方負擔`
- if `progress_delay` intent:
  - `進度落後 逾期 履約期限 暫停付款 違約金 終止契約 解除契約 另覓廠商`

Expansion behavior:
- original query is preserved
- expansion terms are appended separated by newlines

### 8.3 Output language detection
Function:
- `detect_output_language(query)`

Behavior:
- count Chinese characters vs ASCII letters
- return `繁體中文` if Chinese chars >= ASCII letters
- else return `English`

This affects answer generation style, not retrieval.

## 9. Evidence Reweighting and Selection

After raw retrieval, the query pipeline performs a second stage of reranking and selection.

### 9.1 Source weighting
Function:
- `source_weight(item, intents)`

Base weights by source:
- `clause`: `+0.20`
- `subclause`: `+0.15`
- `structured.clause_action_summary`: `+0.22`
- `structured.contract_summary`: `-0.05`
- `structured.milestone_summary`: `-0.08` for action queries, else `0`
- `structured.retention_summary`: `-0.08` for action queries, else `0`
- `structured.validation_risk`: `-0.15` for action queries, else `-0.05`
- `wiki`: `-0.25`

Additional boosts:
- for `action` intent, if text contains any of:
  - `暫停付款`
  - `違約金`
  - `扣罰`
  - `終止`
  - `解除`
  - `另覓廠商`
  - `書面通知`
  - `費用由乙方負擔`
  then `+0.18`
- extra `+0.08` if `structured_kind == clause_action_summary`
- for `progress_delay` intent, if text contains:
  - `進度`
  - `落後`
  - `逾期`
  - `延誤`
  then `+0.08`

### 9.2 Action candidate expansion
Function:
- `expand_related_action_candidates(citations, intents)`

Behavior:
- if no `action` or `progress_delay` intent, return unchanged
- otherwise add source-weight adjustment into `retrieval_score`

### 9.3 Final evidence selection
Function:
- `select_diverse_citations(citations, top_k, intents)`

Process:
1. sort reweighted candidates by adjusted `retrieval_score`
2. partition into:
   - `clause_like` = `clause` + `subclause`
   - `structured`
   - `wiki`
3. seed the final set with clause-like evidence first
4. add structured evidence next, prioritizing `clause_action_summary`
5. skip wiki when clause evidence exists
6. fill remaining slots by descending score

Selection rules currently used:
- if clause evidence exists:
  - push up to `min(max(5, top_k - 2), len(clause_like))`
- structured push limit:
  - `3` for action queries
  - otherwise `2`
- wiki is only added if clause evidence is absent and slots remain

### 9.4 Active filtering before final selection
Inside `answer_with_langchain(...)`, before selection:
- all `wiki` chunk hits are removed
- all `structured_kind == validation_risk` hits are removed

Important implication:
- even though `wiki` and `validation_risk` logic still exist in the codebase, they are intentionally excluded from the active query path

## 10. Prompt Assembly

### 10.1 Structured context injection
Function:
- `build_structured_context(session, contract_ids, intents)`

This always builds a deterministic contract facts section.

Per contract it includes:
- contract name
- source file
- total amount + currency
- payment type
- milestone count
- retention summary if present

Validation warnings:
- included only when query is **not** `action` and not `progress_delay`
- only severities `ERROR` and `WARNING` are included

This means the system suppresses validation warnings for remedy-style queries to avoid noisy retrieval/prompting.

### 10.2 Evidence formatting
Function:
- `format_evidence(citations)`

Output sections:
- `【檢索到的結構化證據】`
- `【原始條款證據】`

Each structured evidence item format:
- `[S#] (structured_kind) text_snippet`

Each clause/subclause evidence item format:
- `[C#] text_snippet (條款=..., 合約=..., 段落=..., 頁~...)`

### 10.3 System prompt behavior
Built in `answer_with_langchain(...)` using `ChatPromptTemplate`.

Current system prompt characteristics:
- Traditional Chinese system prompt
- instructs model to behave as an offline contract analysis assistant
- explicitly says to answer only from:
  - structured context
  - retrieved evidence
- says original clauses should be preferred over other evidence
- warns that chat history is only for resolving references, not facts
- explicitly frames corpus as:
  - Taiwan engineering contracts
  - milestone payment contracts
  - RFPs
  - revised contract versions
- tells model to check common clause families such as:
  - fixed price / no additional claims
  - payment method
  - acceptance
  - delay penalty
  - suspension of payment
  - damages
  - termination / rescission
  - force majeure
  - tariff carve-out
  - warranty
  - subcontracting restrictions
- final answer language must follow the user’s question language:
  - Chinese -> Traditional Chinese
  - English -> English

### 10.4 Dynamic answer instructions
Function:
- `build_answer_instructions(intents, output_language)`

These are appended into the human message block.

Always included:
- answer strictly from evidence
- do not add unseen clauses
- if multiple clauses grant different rights/remedies, list all of them
- cite the supporting clause for each conclusion
- first classify the document type
- pay attention to important engineering-contract clause families
- final answer language must be the detected language

Intent-specific additions:
- `action` / `progress_delay`:
  - list all available actions/remedies
  - include thresholds and whether facts satisfy them
  - preferred answer structure is action list + clause basis + conditions
- `payment`:
  - distinguish payment trigger, acceptance condition, documents, amount, percentage, retention, suspension/set-off rights
- `risk`:
  - prioritize risk families such as delay penalties, suspension, termination, replacement contractor, set-off, damages, warranty, force majeure carve-out, tariff exclusion, customer pass-through liability, no extra claims

## 11. API Query Flow

Defined in `backend/api/query.py`.

### 11.1 Request shape
`QueryPayload` fields:
- `query: str`
- `top_k: int = 12`
- `contract_id: str | None`
- `chat_session_id: str | None`
- `persist_to_wiki: bool = False`

### 11.2 LLM readiness gate
`POST /api/query` refuses to run if `llm_available()` is false.

Response:
- HTTP `503`
- message: local LLM is not ready

There is **no active non-LLM fallback path** for normal query answering.

### 11.3 Contract scope behavior
If `contract_id` is provided:
- query only that contract

Otherwise:
- query all active contracts returned by `get_all_contracts(session)`
- retrieval is still performed per contract, then merged in Python

## 12. Persistence of Query Results

### 12.1 Chat session storage
The answer path persists:
- one human message
- one AI message

### 12.2 Filed query storage
Each query turn is persisted to `FiledQuery` with:
- `query_id`
- `chat_session_id`
- `human_message_id`
- `ai_message_id`
- `question`
- `answer`
- `contract_scope_json`
- `citations_json`
- `wiki_path`
- `answer_method`
- `retrieval_mode`

### 12.3 Wiki note persistence
If `persist_to_wiki=True`:
- query note is written through `append_query_note(...)`
- per-turn linkage is preserved

If `persist_to_wiki=False`:
- `record_query_result(...)` persists the turn without wiki filing

## 13. Known Inactive / Legacy Paths Still Present in Code

The codebase still contains some logic that is not active in the main path:

### 13.1 Wiki chunk builder exists but is not used in `build_chunks()`
- `build_wiki_chunks()` can create wiki chunks
- current active index build does not include them

### 13.2 Validation-risk weighting still exists in `source_weight()`
- `structured_kind == validation_risk` is still recognized
- but those chunks are filtered out before final selection

### 13.3 Wiki support still exists in evidence selection
- `select_diverse_citations()` still knows about wiki chunks
- but query path removes wiki citations before selection

So the current implementation is best described as:
- **document-first retrieval with structured support**
- **wiki-capable codebase, but wiki-disabled active retrieval**

## 14. Practical Strengths and Weaknesses

### Strengths
- Contract-aware query expansion
- Hybrid BM25 + vector fusion
- Source-type reweighting
- Clause vs subclause separation
- Deterministic structured context injection
- Strong prompt guidance for engineering contracts
- Output language follows user language
- LLM-required mode avoids silent fallback answers

### Weaknesses
- Subclause segmentation is still shallow for long numbered legal subsections
- BM25 scores are not surfaced numerically in returned hits
- Structured chunks can still be less precise than raw clauses for legal nuance
- Query intent model is regex-based and limited
- Validation warnings are not part of active retrieval evidence
- Wiki indexing exists in code but is not active
- No dedicated second-stage semantic reranker beyond heuristic weighting

## 15. Current Design Summary

The current system is a **hybrid contract QA pipeline** with these active priorities:

1. Use original contract text first
2. Use structured synthetic summaries as support
3. Avoid wiki dominance in retrieval
4. Avoid non-LLM fallback answers
5. Bias retrieval and prompting toward contract-analyst behavior rather than generic QA

The current active retrieval strategy is therefore:
- build clause/subclause/structured chunks
- index locally and optionally in Qdrant
- expand query by contract intent
- retrieve with BM25 + vectors
- fuse with RRF
- reweight by chunk type and intent
- prefer clause evidence first
- inject deterministic contract structure into the prompt
- answer only when the local LLM is available
