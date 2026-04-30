# Retrieval Fix Plan V2

This plan converts the current root-cause map into an execution order that is safe, measurable, and compatible with the current retrieval stack.

Scope:
- retrieval scoring and selection only
- not generation prompt tuning
- not chunking rewrites
- not broader architecture changes

Primary goal:
- improve retrieval precision and confidence calibration without regressing the current formal-contract wins

Reference baselines:
- best non-reranker baseline: [regression-results-2026-04-30T08-46-24.json](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/5th/regression-results-2026-04-30T08-46-24.json)
- best reranked run so far: [regression-results-2026-04-30T09-08-59.json](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/6th/regression-results-2026-04-30T09-08-59.json)
- scoring explainer: [current-retrieval-scoring.md](/Users/mulia/Desktop/Projects/Intern%20Project/handoff/retrieval/current-retrieval-scoring.md)

## Root Cause Map

| Symptom | Root cause | Stage | Fix |
|---|---|---|---|
| Scores >1.0 in run4 | `source_weight()` adds on top of reranker/base normalized score | Stage 8 | Fix 1 |
| `01XX` BM25 = 0 across runs | tokenizer mismatch or token sparsity for this contract | Stage 3.1 | Fix 2 |
| Q8 subcontracting weak on `01XX/03XX/04XX` | subcontracting is not a first-class intent in the restored baseline | Stages 1, 2, 8 | Fix 3 |
| Non-formal legal queries return weak approximations | no abstention mechanism when no real lexical anchor exists | Stage 9 | Fix 4 |
| `03XX Q4` regressed badly in reranked run | reranker has dominant weight and no protected floor for strong pre-rerank hits | Stage 7 | Fix 5 |
| Tail citations survive at very low scores | candidate pool is wide but there is no relative score floor before final selection | Stages 4, 9 | Fix 6 |
| `05XX Q9` appears to skip top rank | dedup or threshold filter is silently dropping candidates with no reason visibility | Stage 9 | Fix 7 |

## Principles

1. Fix score calibration before adding new heuristics.
2. Diagnose BM25 before trying to “improve retrieval” globally.
3. Add abstention for non-formal legal-style queries rather than forcing approximations.
4. Preserve current wins on `02XX` and `05XX`.
5. Avoid broad weight increases; prefer floors, normalization, and gating.

## Critical Fixes

### Fix 1 — Normalize candidate scores after source weighting

Stage:
- Stage 8
- [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Problem:
- reranker/base blending yields a bounded normalized score
- `source_weight()` then adds extra unbounded bonuses
- downstream thresholds and cross-run comparisons stop meaning what they appear to mean

Current effect:
- a candidate can exceed `1.0`
- threshold logic becomes inconsistent
- score distributions across runs become incomparable

Plan:
1. Introduce a helper to normalize weighted candidate scores by max score.
2. Apply it after `source_weight()` is added to all candidates.
3. Do not clip scores at `1.0`; preserve relative spacing.
4. Keep raw component scores in metadata for debugging.

Implementation target:
- after `expand_related_action_candidates()` or at the beginning of `select_diverse_citations()`
- before any thresholding or diversity logic

Expected effect:
- final working candidate scores return to `[0,1]`
- thresholds regain meaning
- reranked vs non-reranked comparisons become interpretable again

Validation queries:
- all retrieval-only regressions
- explicitly inspect `top_score`, `min_selected_score`, and whether any selected score exceeds `1.0`

### Fix 2 — Diagnose and repair BM25 tokenization for `01XX`

Stage:
- Stage 3.1
- [indexer.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/indexer.py)

Problem:
- `01XX` repeatedly shows BM25 collapse behavior
- likely cause is empty or near-empty token lists for many chunks
- this makes the lexical side structurally weak for that document

Plan:
1. Add tokenizer diagnostics during indexing or retrieval debug mode:
   - empty token count
   - average tokens per chunk
   - sample chunks with empty token output
2. Inspect whether the current tokenizer fails on:
   - punctuation-heavy sections
   - mixed Chinese/English
   - unusual encoding normalization
3. Add a fallback tokenizer path when primary tokenization yields too few tokens:
   - regex token extraction for alnum/CJK sequences
   - last-resort short character-level fallback
4. Reindex affected contracts after the tokenizer change.

Expected effect:
- `01XX` BM25 should stop being structurally dead
- lexical anchors for payment/risk/overview should start contributing again

Validation queries:
- `01XX Q2`
- `01XX Q5`
- `01XX Q10`
- compare BM25 hit presence before and after

### Fix 3 — Add subcontracting as a first-class intent

Stages:
- Stage 1
- Stage 2
- Stage 8
- [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Problem:
- subcontracting/assignment is a recurring weak area
- current restored baseline does not treat it as a dedicated intent
- therefore no dedicated query expansion, no family shaping, no anchor-aware handling

Plan:
1. Add `subcontracting` intent detection regex.
2. Add `QUERY_EXPANSIONS['subcontracting']`.
3. Add exact-match anchor terms for subcontracting.
4. Add intent-specific source weighting:
   - family bonus for subcontract/assignment-like chunks
   - smaller lexical-anchor bonus when exact terms appear
5. Register subcontracting in the abstention anchor check from Fix 4.

Expected effect:
- `Q8` retrieval on formal contracts should become sharper
- `Q8` on non-formal docs should abstain more often instead of returning random technical sections

Validation queries:
- `01XX Q8`
- `03XX Q8`
- `04XX Q8`
- `05XX Q8`

### Fix 4 — Anchor gating and abstention for non-formal legal-style queries

Stage:
- Stage 9
- [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Problem:
- current system tends to always return something
- on non-formal docs, this produces weak approximations for legal/commercial queries that are not actually covered by the source

Plan:
1. Define anchor-term sets for the following intents:
   - subcontracting
   - progress_delay
   - force_majeure
   - payment
2. Define document-type-specific score floors:
   - formal
   - non-formal
3. Before generation handoff and optionally before final evidence selection, check:
   - top score meets minimum confidence floor
   - top evidence contains at least one lexical anchor for the active intent
4. If anchor check fails:
   - set retrieval metadata to low-confidence
   - inject an abstention note for generation
   - optionally reduce the citation set to only summary evidence or return fewer citations

Expected effect:
- non-formal legal-style questions stop forcing bad evidence into the answer
- generation becomes more likely to say `文件未明確規定` instead of hallucinating remedy logic

Validation queries:
- `01XX Q4`
- `01XX Q8`
- `03XX Q4`
- `03XX Q8`
- `03XX Q6`

## High Priority Fixes

### Fix 5 — Reranker floor to protect strong pre-rerank candidates

Stage:
- Stage 7
- [reranker.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/reranker.py)

Problem:
- reranker blend currently dominates (`0.7` rerank / `0.3` base)
- a strong base candidate can be catastrophically demoted if reranker dislikes it
- observed on `03XX Q4`

Plan:
1. Identify top-N pre-rerank candidates by base normalized score.
2. After rerank blending, prevent those candidates from falling past a configurable floor band.
3. Use a rank-based protection rule rather than hard pinning rank 1.
4. Keep the reranker dominant overall, but prevent obvious collapses.

Expected effect:
- reranker still improves ordering where candidates are all plausible
- but does not catastrophically erase strong pre-rerank evidence

Validation queries:
- `03XX Q4`
- `04XX Q7`
- `05XX Q2`

### Fix 6 — Relative score floor to drop tail citations

Stages:
- Stage 4
- Stage 9
- [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Problem:
- many low-value tail candidates survive deep into the pipeline
- they add noise and can be selected during diversity backfill

Plan:
1. After score normalization, compute the top candidate score.
2. Drop candidates below a relative threshold, e.g. `25%` of the top score.
3. Keep a guardrail so we do not return fewer than `top_k` if the pool is already small.
4. Log how many candidates were removed for visibility.

Expected effect:
- cleaner final evidence set
- fewer weak rank-30+ items drifting into results
- less burden on generation

Validation queries:
- inspect rank distribution on all contracts
- confirm removal of low-score tail citations

## Medium Priority Diagnostic Fix

### Fix 7 — Log dedup / threshold drops in final selection

Stage:
- Stage 9
- [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py)

Problem:
- there is a known suspicion that top-ranked candidates can vanish silently during dedup or final filtering
- `05XX Q9` is the clearest observed symptom

Plan:
1. Add debug logging inside final selection.
2. Log dropped candidates with:
   - prior rank
   - score
   - reason
   - text prefix
3. Keep logs bounded to avoid flooding.
4. Use this as a diagnostic step first, not a logic change.

Expected effect:
- clarifies whether the issue is duplication, threshold filtering, or push-order side effects

Validation queries:
- `05XX Q9`
- any query where visible rank numbering appears to skip strong candidates

## Implementation Order

This is the order to execute in code.

1. Implement Fix 1.
2. Implement Fix 2.
3. Implement Fix 6.
4. Implement Fix 3.
5. Implement Fix 4.
6. Implement Fix 5.
7. Implement Fix 7.

Rationale:
- Fix 1 makes scores interpretable.
- Fix 2 restores a missing lexical channel.
- Fix 6 removes obvious tail noise before more semantic tuning.
- Fix 3 and Fix 4 address the biggest remaining semantic gap.
- Fix 5 stabilizes reranking after the candidate pool is healthier.
- Fix 7 gives visibility into residual oddities.

## Validation Plan

### Retrieval-only regression after each cluster

Run after:
- Fixes 1–2
- Fixes 3–4
- Fixes 5–7

Primary queries to inspect:
- `01XX Q2`
- `01XX Q5`
- `01XX Q8`
- `03XX Q4`
- `03XX Q6`
- `03XX Q8`
- `04XX Q7`
- `04XX Q8`
- `05XX Q2`
- `05XX Q9`

### Success criteria

Fix 1:
- no selected retrieval score exceeds `1.0`

Fix 2:
- `01XX` has meaningful BM25 participation

Fix 3:
- `Q8` is no longer treated like a generic query

Fix 4:
- weak non-formal legal-style queries abstain more often instead of returning random technical sections

Fix 5:
- reranker no longer causes obvious collapses like `03XX Q4`

Fix 6:
- tail citations below relative floor are removed from final outputs

Fix 7:
- any rank drop in `05XX Q9` becomes explainable from logs

## What Not To Do

1. Do not raise `source_weight()` values further.
   - The scoring stack is already sensitive to heuristic overreach.
   - Fix 1 is about calibration, not stronger boosts.

2. Do not increase `candidate_k` above the current effective width.
   - Reranker throughput is already a constraint.
   - Better candidate quality matters more than bigger pools.

3. Do not tune formal-contract queries broadly right now.
   - `02XX` and `05XX` are already strong enough to serve as guardrails.
   - Broad tuning there risks unnecessary regression.

## Expected Outcome

If the plan works, the system should end up with:
- calibrated scores
- less BM25 blindness on `01XX`
- cleaner subcontracting retrieval behavior
- stronger abstention on non-formal legal-style questions
- safer reranking
- fewer useless tail citations
- better debug visibility into final selection behavior

That would move the current bottleneck from retrieval precision to generation discipline in a more defensible way.
