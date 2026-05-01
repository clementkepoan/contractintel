# Heuristic Weight Table Audit

This note defines the current audit procedure for `source_weight()` in [langchain_query.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/langchain_query.py).

## Scope

- Target: heuristic weighting only
- Do not modify:
  - anchor gating
  - reranker blend
  - retrieval candidate width
  - summary injection

## Baseline

Use these as the baseline references before zeroing the table:

- Original retrieval set, latest stable branch:
  - [retrieval 8th](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval/8th/regression-results-2026-04-30T15-23-02.json)
- Varied retrieval set, latest run before zeroing:
  - [retrieval query2 run4](/Users/mulia/Desktop/Projects/Intern%20Project/regression_test/retrieval_query2/run4/regression-results-2026-04-30T20-03-16.json)

For this audit, treat `retrieval_query2/run4` as the primary control because it exposes current brittleness more clearly than the original prompt set.

## Current table size

Current `source_weight()` contains **31** explicit `weight +=` / `weight -=` operations.

That count excludes:
- local variable setup
- family-set construction
- return statement

## Current categories in the table

The 31 operations fall into these groups:

1. Base chunk-type preferences
- clause / section
- subclause / requirement
- structured
- wiki

2. Structured summary preferences
- clause action summary
- overview summary boosts
- risk summary boosts
- payment summary boosts
- acceptance summary boosts
- price-adjustment summary boost
- force-majeure summary boost
- contract / milestone / retention / validation penalties

3. Intent-specific lexical or family boosts
- action
- progress_delay
- payment
- acceptance
- risk
- price_adjustment
- force_majeure
- subcontracting

4. Non-formal special handling
- BM25-present bonus
- exact lexical anchor bonus

## Audit procedure

### Step 1
Keep current branch behavior as the control.

### Step 2
Zero the weight table completely:

- `source_weight()` returns `0.0`
- all old weighting logic is removed from execution

This change has now been applied in code.

### Step 3
Run the same retrieval regressions again and save them separately.

Required comparisons:
- original retrieval set
- varied retrieval set

### Step 4
Only after the zero-weight run is available:
- identify regressions
- restore one weight at a time only for cases that clearly need it
- document each reinstated weight with:
  - what it does
  - which regression case needs it
  - why reranker and base retrieval were insufficient

## Hard rule for reinstatement

Do not restore weights because they “seem useful.”

Restore only if:
1. a specific regression appears after zeroing
2. re-enabling one specific weight removes that regression
3. the same fix does not create broader new regressions

If that standard is not met, the weight stays deleted.

## Current recommendation

This audit is worth doing.

Why:
- the weighting layer is now large enough to hide real retrieval behavior
- recent tuning risks brittleness
- zeroing the table is the fastest honest way to see what is actually load-bearing

What this audit should answer:
- whether reranker + base hybrid retrieval already do most of the work
- whether summary weighting is truly necessary
- whether some current “fixes” are just noise
