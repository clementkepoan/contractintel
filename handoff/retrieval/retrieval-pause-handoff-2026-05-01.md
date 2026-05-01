# Retrieval Pause Handoff

Date:
- 2026-05-01

Scope:
- This handoff freezes the current retrieval state before switching focus to generation-model experiments.
- The immediate next user task is to test generation quality with a weaker query model using the varied regression set.

---

## Current retrieval state

Relevant implementation file:
- [backend/pipeline/langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Relevant supporting notes:
- [handoff/retrieval/current-retrieval-scoring.md](/Users/mulia/Desktop/Projects/Intern%20Project/handoff/retrieval/current-retrieval-scoring.md)
- [handoff/retrieval/weight-table-audit.md](/Users/mulia/Desktop/Projects/Intern%20Project/handoff/retrieval/weight-table-audit.md)

---

## What is currently implemented

### Retrieval architecture still in place
- hybrid retrieval
- Qdrant vector search
- BM25 retrieval
- reranker via `/v1/rerank`
- summary injection for non-formal docs
- anchor gating / abstention for `action`, `force_majeure`, `subcontracting`
- low-confidence metadata

### Important current logic
- `source_weight()` is currently **fully zeroed** — confirmed not load-bearing by audit
- anchor gating remains active
- reranker blend remains active
- summary injection remains active
- action / force-majeure / subcontracting confidence checks remain active

---

## Completed work (do not revisit)

### ✅ Priority 1 — Anchor gating for non-formal legal queries
Status: **Done**

What was done:
- extended anchor gating to `action` / remedy queries on non-formal docs
- consistent with existing `force_majeure` and `subcontracting` abstention logic
- system now returns `missing_anchor:action` instead of 10 weak technical chunks with false confidence

Result:
- `03XX Q4` moved from false-confidence technical evidence to `missing_anchor:action`
- `01XX Q4` behavior similarly improved
- abstention is now active for all three high-risk non-formal legal query classes

### ✅ Priority 2 — Heuristic weight table audit and deletion
Status: **Done**

What was done:
- zeroed the entire `source_weight()` function
- ran full regression on both varied set and original set
- traced regressions case by case
- conclusion: no weight entry survived justification check

Key finding:
- the heuristic weight table was **not load-bearing overall**
- strong formal-contract retrieval held without it
- abstention behavior on weak non-formal queries held without it
- one brittle case actively improved after deletion

Practical outcome:
- `source_weight()` stays at `0.0`
- the table is not restored
- if any entry is ever reinstated, it requires a specific regression case as justification

---

## Remaining priorities

### Priority 3 — Intent classification robustness
Status: **Not started**

What this means:
- replace or supplement the current regex-based classifier in `classify_query_intents()`
- intent errors are silent and multiplicative — they corrupt expansion, boosting, summary injection, anchor gating, and diversity selection all at once
- the `承包` regression is proof this is not theoretical

Recommended approach:
- start with a few-shot LLM classification call as a drop-in replacement
- or embedding similarity against canonical intent examples if latency matters
- do not let the regex table grow further in the meantime

Hard constraint:
- do not expand the existing regex phrase lists to patch new misclassifications
- log misclassifications instead, use them as training signal

### Priority 4 — Candidate quality improvements
Status: **Not started — blocked on Priority 3**

What this means:
- improve what enters the top ~40 candidate pool before reranking
- better chunking strategy for non-formal docs
- possibly stricter document-type-aware pre-filtering

Important constraint:
- do not attempt this until intent classification is more stable
- candidate quality changes must be measured against the current clean zeroed-weight baseline, not a heavily tuned heuristic stack
- be cautious about pre-rerank semantic filtering — hard cuts before the reranker can permanently remove the right answer from the pool

### Priority 5 — Multi-contract retrieval scaling
Status: **Not started**

What this means:
- reranker candidate breadth is currently capped at roughly `candidate_k` regardless of how many contracts are searched
- single-contract and multi-contract queries have asymmetric evidence quality
- users won't know why multi-contract answers are worse

Recommended fix:
- scale candidate pool proportional to number of selected contracts before reranking

---

## Important retrieval baselines

### Earlier useful baselines
- Strong reranked baseline on original retrieval set:
  - [retrieval 6th](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/6th/regression-results-2026-04-30T09-08-59.json)
- Safer abstention branch on original retrieval set:
  - [retrieval 8th](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/8th/regression-results-2026-04-30T15-23-02.json)
- Varied-set baseline before zero-weight audit:
  - [retrieval query2 run4](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval_query2/run4/regression-results-2026-04-30T20-03-16.json)

### Zero-weight audit runs
- Varied set with `source_weight() = 0.0`:
  - [regression-results-2026-04-30T20-20-19.json](/Users/mulia/Downloads/regression-results-2026-04-30T20-20-19.json)
- Original set with `source_weight() = 0.0`:
  - [regression-results-2026-04-30T20-32-30.json](/Users/mulia/Downloads/regression-results-2026-04-30T20-32-30.json)

---

## What is currently strong

### Strong or mostly stable after zeroing
- `05XX Q2`, `Q4`, `Q7`, `Q8`
- `05XX V2`, `V4`, `V7`, `V8`
- `04XX Q2`, `V2`

Interpretation:
- these cases are carried by base hybrid retrieval, reranker, and explicit clause structure
- not by the old heuristic weight table

---

## What is currently weak

### Still weak / unresolved
- `04XX Q7`, `V7`
- `04XX Q8`, `V8`
- `01XX Q8`, `V8`
- `03XX Q8`, `V8`

### Weak but now more honest (abstention working correctly)
- `03XX Q4`, `V4`
- `01XX Q4`, `V4`

Interpretation:
- non-formal documents remain the hardest class for legal/remedy-style queries
- anchor gating now prevents false-confidence behavior on the worst cases
- the remaining weak cases are honest failures, not silent wrong answers

---

## Retrieval honesty improvements achieved (preserve these)

1. `missing_anchor:*` low-confidence detection for `force_majeure`, `subcontracting`, `action`
2. low-confidence fallback on non-formal docs — return fewer, safer citations instead of 10 weak chunks
3. force-majeure reason cleanup — `V7` queries now correctly fail as `missing_anchor:force_majeure`
4. subcontracting classifier cleanup — removed over-broad `承包` trigger
5. heuristic weight table deleted — cleaner baseline, one less source of silent regression

---

## What should not be touched next

Unless there is new regression evidence, do not spend time on:

1. restoring the old heuristic weight table in any form
2. adding new ad hoc weighting boosts
3. adding per-document fallback hacks
4. further retrieval tuning to rescue `V4` on non-formal docs
5. expanding regex phrase lists to patch intent misclassifications

Reason:
- diminishing returns are already visible at this layer
- the audit confirmed the weight table was mostly noise
- further heuristic accumulation risks overfitting and makes the system harder to reason about

---

## Recommended next focus

Move focus to generation experiments.

Planned experiment:
- use the same model for query generation as extraction
- run generation regression on the varied set

Reason:
- retrieval is now clean enough to pause
- the bigger remaining uncertainty is generation quality versus model capability
- generation experiments will produce signal that is independent of retrieval tuning

---

## Short operational summary

| Component | Current state |
|---|---|
| `source_weight()` | Zeroed — keep deleted |
| Anchor gating | Active — do not touch |
| Reranker | Active — do not touch |
| Summary injection | Active — do not touch |
| Intent classifier | Regex — freeze, plan replacement |
| Candidate quality | Unmeasured cleanly — do after intent work |
| Multi-contract scaling | Known gap — low urgency now |