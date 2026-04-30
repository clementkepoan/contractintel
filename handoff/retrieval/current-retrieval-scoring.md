# Current Retrieval Scoring and Failure Modes

This note explains how retrieval works **right now** in the project, how scores are constructed, what each weighting step is trying to do, and where the system is currently strong or weak.

The goal is to make the current behavior legible before making more tuning changes.

## High-level pipeline

For a query, retrieval currently runs in these stages:

1. Classify query intents.
2. Expand the query with hardcoded related terms.
3. Retrieve per-contract candidates with hybrid BM25 + vector retrieval.
4. Inject structured summary chunks for some non-formal document intents.
5. Optionally expand from subclause to parent clause for formal contracts.
6. Aggregate candidates across selected contracts.
7. Rerank the aggregated candidates with the reranker model.
8. Apply additional heuristic source weighting.
9. Select a diverse final top-k evidence set.
10. Pass the final evidence into generation.

Relevant code:
- [backend/pipeline/langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)
- [backend/pipeline/indexer.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/indexer.py)
- [backend/pipeline/reranker.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/reranker.py)

## Stage 1: Query intent classification

Defined in `classify_query_intents()`.

Current intents:
- `action`
- `overview`
- `progress_delay`
- `payment`
- `acceptance`
- `risk`
- `price_adjustment`
- `force_majeure`

This is regex-based, not model-based.

Examples:
- `如果乙方進度落後或遲延履約...` -> `action`, `progress_delay`
- `這份文件主要是在規範什麼？` -> `overview`
- `付款方式是什麼？` -> `payment`
- `哪些情況可以主張不可抗力？` -> `force_majeure`

### Why this exists

The retrieval stack is not one generic semantic search. It is intentionally intent-sensitive.

This allows later stages to:
- expand the query differently
- boost different chunk families
- inject different summary chunks
- apply different diversity behavior

### Failure mode

If intent classification misses the real query type, all downstream weighting drifts.

Example:
- a query that is really about `subcontracting` is currently not a first-class intent in the restored baseline.
- that means no dedicated lexical/semantic shaping exists for it.

## Stage 2: Query expansion

Defined in `expand_query()` and `QUERY_EXPANSIONS`.

The system appends extra lexical terms based on detected intents.

Examples:
- `payment` adds terms like `付款 給付 工程款 請款 期款`
- `risk` adds `風險 違約 違約金 扣罰 賠償 逾期 固定總價 不得追加`
- `price_adjustment` adds `固定總價 不得追加 不得調整 法令變更 情事變更 單價`
- `force_majeure` adds `不可抗力 關稅措施 情事變更 免責 不補償 終止`

There are also fallback expansions for:
- `action`
- `progress_delay`
- `price_adjustment`
- `force_majeure`

### Why this exists

BM25 and vector retrieval both benefit from slightly richer lexical signals, especially for legal or contract-style clauses that may use neighboring wording rather than the exact user phrasing.

### Failure mode

Hardcoded expansions can over-broaden the candidate set.

This is especially risky on non-formal documents such as:
- RFPs
- technical specs
- construction instructions

because the expansion terms may have no real clause anchor in the source, and the retriever still returns vaguely related technical sections.

## Stage 3: Hybrid retrieval inside `hybrid_search_chunks()`

This is the core retrieval stage.

### 3.1 BM25 side

For the current contract:
- tokenize all chunks
- build `BM25Okapi`
- score the query
- keep top `top_k`

Current code path:
- `BM25Okapi(tokenized_chunks)`
- `get_scores(tokenize(query))`

### 3.2 Vector side

The vector side first tries Qdrant:
- `qdrant_vector_search(contract_id, query, top_k)`

If Qdrant is not available, it falls back to local vector search over stored embeddings.

### 3.3 Fusion method

The system fuses BM25 and vector rankings using reciprocal rank fusion (RRF):

`score += 1 / (k + rank_position)` with `k = 60`

Important:
- RRF uses **rank position**, not raw score magnitude.
- This makes the fusion robust to absolute score-scale differences across retrievers.

### 3.4 Additional normalized score bonuses

After RRF, the system adds small normalized bonuses from BM25 and vector scores.

For each candidate chunk:

`combined_score = rrf_score + bm25_weight * bm25_norm + vector_weight * vector_norm`

Where:
- `bm25_norm` and `vector_norm` are min-max normalized **within the current candidate lists**
- this means raw score magnitude is not used directly

Current weights:

For formal contracts:
- `bm25_weight = 0.15`
- `vector_weight = 0.10`

For non-formal docs (`spec_rfp`, `instruction_manual`, `mixed`):
- `bm25_weight = 0.28`
- `vector_weight = 0.06`

### Why this exists

RRF gives robust rank fusion, while the normalized bonuses let the system prefer:
- strong lexical hits on non-formal docs
- a more balanced hybrid signal on formal contracts

### Important implication about the new embedding model

If the new embedding model returns higher raw similarity numbers, that does **not** automatically overweight vector retrieval.

Why:
- the vector score is only used after min-max normalization within the top vector candidate set
- the bigger effect of a new embedding model is changing **which chunks enter the top vector set**, not the absolute scale itself

### Failure modes

1. If BM25 top-k is poor, the lexical side contributes little meaningful structure.
2. If vector top-k is semantically broad, RRF can still admit weak candidates.
3. On non-formal docs, broad technical sections may still beat a clean abstention behavior.

## Stage 4: Candidate pool width

This is important for understanding reranking.

In `retrieve_query_evidence()`:

`candidate_k = max(top_k * 4, 24)`

So if UI `top_k = 10`:
- `candidate_k = 40`

Per selected contract, the hybrid retriever pulls about **40 chunk candidates**.

This means the reranker is not reranking only 10 items. It is reranking roughly 40 items per single-contract query.

### Limitation

If multiple contracts are searched at once:
- all contract candidates are aggregated first
- reranker top_n is still capped to about `candidate_k`

So multi-contract rerank breadth is currently more constrained than single-contract rerank breadth.

## Stage 5: Summary chunk injection for non-formal docs

Defined via `summary_injection_base_score()` and the injection block inside `hybrid_search_chunks()`.

This only applies for non-formal document types and only for intents such as:
- `overview`
- `risk`
- `payment`
- `acceptance`
- `price_adjustment`
- `force_majeure`

Injected chunk types:
- `wiki_llm_summary`
- `wiki_contract_summary`

Example base scores:

Overview:
- `契約目的`, `At A Glance` -> `0.36`
- other `wiki_contract_summary` -> `0.30`
- otherwise -> `0.24`

Payment:
- `商務與付款`, `Milestone And Payment Structure`, `Payment Procedures And Commercial Notes` -> `0.34`
- otherwise -> `0.22`

Risk:
- `風險與注意事項`, `Risks And Open Issues` -> `0.34`
- otherwise -> `0.24`

### Why this exists

Non-formal docs often do not have clean contract-style clause structure.

Summary chunks give retrieval a stable semantic anchor for:
- what the file is about
- what is missing commercially
- what the major risk/payment/acceptance themes are

### Failure mode

Summary chunks can bleed into the wrong query type.

Observed earlier:
- risk summaries outranked better payment or overview chunks in some non-formal cases

This is why summary injection is useful but fragile.

## Stage 6: Parent expansion

This applies only to formal contracts.

For eligible high-scoring `subclause` hits:
- look up their parent clause
- add the parent back as a candidate
- parent score = child score × multiplier

Current settings:

Non-formal docs:
- disabled entirely

Formal action/progress queries:
- cap = `2`
- threshold = `0.04`
- multiplier = `0.65`

Other formal queries:
- cap = `3`
- threshold = `0.02`
- multiplier = `0.85`

### Why this exists

A small matched child chunk can carry the full parent clause back into evidence, improving context completeness.

### Known tradeoff

This helped:
- clause-specific payment/detail questions

But it previously hurt:
- action/progress questions

because it consumed evidence slots that should have gone to diverse remedy clauses.

That is why action-like formal queries use a more conservative expansion policy now.

## Stage 7: Reranking

Implemented in `backend/pipeline/reranker.py`.

Current endpoint:
- `POST /v1/rerank`

Configured model:
- `Qwen3-Reranker-0.6B-mlx-8Bit`

### How reranking works

For each citation, the reranker sees a document string roughly like:

`<label>\n<text_snippet>`

Then rerank scores are normalized and combined with the existing retrieval score:

`final_score = 0.7 * rerank_norm + 0.3 * base_norm`

So reranker has the dominant say once it runs.

### Why this exists

The retrieval stack often produced plausible candidates but incorrect ordering.

Reranking is meant to fix exactly that:
- payment clause above suspension clause
- overview chunk above risk chunk
- more exact topical ordering among already plausible candidates

### Observed effect

Strong win:
- `05XX Q2` payment ordering

Partial wins:
- `02XX Q2`
- `03XX Q1`
- `01XX Q2`

Weaknesses remain:
- `01XX Q8`
- `03XX Q8`
- `04XX Q8`
- `04XX Q7` can still misorder

### Important limit

Reranker cannot rescue a candidate set that has no real anchor-bearing evidence.

If the top 40 candidates are all weak approximations, reranking only rearranges weak approximations.

## Stage 8: Heuristic source weighting (`source_weight()`)

After reranking, the system still adds heuristic source weights before final selection.

This is a major part of the current behavior.

### Base chunk-type preferences

- `clause`, `section` -> `+0.20`
- `subclause`, `requirement` -> `+0.15`
- `structured` -> varies by kind
- `wiki` -> `-0.25`

### Structured chunk preferences

`clause_action_summary`:
- `+0.22`

`wiki_llm_summary` / `wiki_contract_summary`:
- overview intent -> `+0.18`
  - `契約目的`, `At A Glance` -> additional `+0.10`
  - `風險與注意事項`, `Risks And Open Issues` -> `-0.03`
- risk intent with matching families -> `+0.16`
  - risk labels get extra `+0.08`
- payment intent with matching families -> `+0.16`
  - payment labels get extra `+0.08`
- acceptance intent with matching families -> `+0.16`
  - acceptance labels get extra `+0.08`
- price adjustment / force majeure -> `+0.18`

Penalties:
- `contract_summary` -> `-0.05`
- `milestone_summary` -> `-0.08` for action
- `retention_summary` -> `-0.08` for action
- `validation_risk` -> `-0.15` for action, otherwise slight downweight

### Intent-specific boosts

- `action` and matching terms such as `暫停付款`, `違約金`, `終止`, `解除` -> `+0.18`
- `progress_delay` with terms like `進度`, `落後`, `逾期`, `延誤` -> `+0.08`
- `payment` + matching clause families -> `+0.10`
- `acceptance` + family match -> `+0.14`
- `risk` + family match -> `+0.10`
- `price_adjustment` + family match -> `+0.16`
- `force_majeure` + family match (formal only) -> `+0.16`

### Non-formal special handling

For `spec_rfp`, `instruction_manual`, `mixed`:
- if `bm25_score > 0` -> `+0.10`
- if label/text contains exact intent match terms -> `+0.18`

### Why this exists

This is the current heuristic layer that tries to encode domain knowledge such as:
- clause-like sources are usually stronger than wiki pages
- payment summary sections are good for payment questions
- risk summary sections are good for risk questions
- exact lexical anchors matter more on non-formal docs

### Failure mode

This is also where the system is easiest to overtune.

Examples of past regressions:
- non-formal risk summaries bleeding into payment or overview
- summary-heavy answers where clause evidence should dominate
- overly broad family boosts on technical documents

## Stage 9: Diversity selection (`select_diverse_citations()`)

This is the final evidence assembly stage.

The function does not simply take top-k by score.

It applies a staged selection policy:

1. Prefer certain structured chunks early for non-formal docs on summary-like intents.
2. Prefer clause-like chunks.
3. Add some structured chunks again if needed.
4. Only use wiki chunks if clause-like evidence is absent.
5. Preserve one non-formal BM25-backed hit if available.

### Specific behavior

For non-formal docs on intents like overview/risk/payment/acceptance/price adjustment/force majeure:
- up to 3 structured summary chunks can be pushed early

Clause-like push:
- formal docs: roughly `top_k - 2`, but at least 5
- non-formal docs: roughly `top_k - 3`, but at least 5

Then backfill from ordered results until top_k is filled.

Finally, for non-formal docs, one BM25-supported candidate may be forced in if it looks useful.

### Why this exists

This is trying to avoid two bad extremes:
- all summary/no raw evidence
- all raw evidence/no high-level clue on non-formal docs

### Failure mode

The selector can still preserve repetitions or weak clause-like evidence if the candidate pool itself is poor.

This is why some non-formal legal-style queries still look bad even after reranking.

## Current strengths

Based on the retrieval regressions, the system is strongest on **formal contracts with explicit clause structure**.

### Strong cases

`02XX`:
- payment retrieval is good
- force majeure / tariff retrieval is usable
- milestone/payment structure is strong

`05XX`:
- payment retrieval is now strong with reranker
- action/progress retrieval is strong
- force majeure retrieval is strong
- subcontracting retrieval is usable

### Why these work

Because the system assumptions match the documents:
- explicit clauses
- clean legal/commercial structure
- clause families align with real content
- parent expansion and reranking have something meaningful to work with

## Current weaknesses

The system is weakest on **non-formal documents** for **legal-style questions that do not have real anchors in the source**.

### Weak cases

`01XX`:
- `Q4` action/remedy
- `Q8` subcontracting/assignment

`03XX`:
- `Q4` action/remedy
- `Q8` subcontracting/assignment

`04XX` (formal, but weaker than 02/05):
- `Q7` force majeure / price-adjustment style interpretation
- `Q8` subcontracting / assignment

### Why these fail

1. The document does not actually contain strong clause anchors.
2. Query expansion broadens the search anyway.
3. Hybrid retrieval still returns the least-bad technical sections.
4. Reranker can only reorder what it was given.
5. Final selection still has to return something unless abstention is stronger.

## Best retrieval outputs so far

If we ignore the test-number labels and judge by behavior:

### Best non-reranker baseline
- [regression-results-2026-04-30T08-46-24.json](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/5th/regression-results-2026-04-30T08-46-24.json)

This is the restored balanced baseline before reranker activation.

### Best overall retrieval output so far
- [regression-results-2026-04-30T09-08-59.json](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/6th/regression-results-2026-04-30T09-08-59.json)

Why:
- reranker was actually active
- fixed important formal-contract ordering issues
- especially `05XX Q2`

But it is not a universal win:
- non-formal subcontracting remains weak
- `04XX Q7` is still unstable

## The real current situation

The retrieval stack is no longer suffering from the original catastrophic issue of chunk collapse.

That problem was fixed by:
- document-type-aware chunking
- better non-formal labels
- summary chunk injection

The current bottleneck is now more specific:

1. **candidate quality on non-formal legal-style queries**
2. **when to abstain instead of returning weak approximate evidence**
3. **a few formal-contract ordering edge cases**

## What this means for future tuning

The next useful retrieval improvements should be narrow, not broad.

Good targets:
- stronger abstention / anchor gating for non-formal legal-style queries
- safer handling of subcontracting-like questions where no real anchor exists
- formal-contract edge cleanup like `04XX Q7`

Bad targets:
- another broad round of weight fiddling everywhere
- relying on generation to compensate for weak evidence

## Bottom line

The current scoring system is a layered stack:
- rank-based hybrid retrieval
- light normalized score bonuses
- optional summary injection
- optional parent expansion
- reranker dominance
- heuristic source weighting
- diversity-aware final selection

It is strongest when the document actually contains well-formed contract clauses.
It is weakest when the query asks legal/commercial questions of non-formal technical documents that never wrote those clauses down in the first place.

That is the current state.
