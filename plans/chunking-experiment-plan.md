## Chunking Experiment Plan

### Goal
Evaluate whether token-aware recursive chunking improves retrieval quality enough to justify replacing or partially replacing the current structure-aware splitter.

This is a **deferred retrieval experiment**. Do not run it while generation prompt work is still moving.

## Current state

### Current chunking behavior
- Formal contracts:
  - clause-grouped first
  - then split with character-based overlap
  - config default: `CHUNK_SIZE=800`, `CHUNK_OVERLAP=100`
- Non-formal documents:
  - section-grouped first
  - then split with capped character-based overlap
  - effective cap: `520` chars with `80` chars overlap
- Structured summary chunks:
  - generated separately
  - not controlled by the main chunk splitter

### Important constraint
Current chunking is:
- structure-aware
- character-based
- not token-based
- not a generic recursive token chunker

So any chunking experiment is a **major retrieval change** and requires full reindexing.

## Why this is deferred

Do not run this experiment now because it would confound:
- generation prompt changes
- retrieval simplification freeze
- embedding/reranker stabilization

The correct sequence is:
1. freeze current generation baseline
2. finish current generation iteration
3. only then run chunking experiments

## Hypothesis

The best plausible use of recursive token chunking is **not** to replace the whole pipeline blindly.

Most likely useful targets:
- non-formal documents (`01XX`, `03XX`)
- weak section-level semantic retrieval
- noisy fallback evidence sets

Less likely useful target:
- formal contracts, where clause grouping is already structurally strong

## Experiment variants

### Variant A: Non-formal only, token-aware split inside grouped sections
Keep:
- current non-formal section grouping
- current structured chunks
- current summary injection

Change only:
- replace `split_text_with_overlap(...)` inside non-formal grouped sections
- use token-based recursive splitting with:
  - target chunk size: `800 tokens`
  - overlap: `400 tokens`

Why this is the safest first test:
- isolates the weak document class
- preserves the current structure-aware grouping
- avoids damaging formal-contract performance unnecessarily

### Variant B: Formal + non-formal token-aware split inside grouped sections
Keep:
- clause grouping for formal contracts
- section grouping for non-formal docs

Change:
- use token-based splitting inside each grouped clause/section body

This is broader than Variant A and should only be tested if A shows promise.

### Variant C: Fully generic recursive token chunking over raw document flow
Do not test first.

Why:
- highest regression risk
- destroys current clause/section structure assumptions
- likely to hurt formal-contract retrieval and citation clarity

## Success criteria

The experiment is only worth keeping if it improves retrieval on weak cases **without** materially hurting strong formal cases.

### Weak-case target rows
- `01XX Q4`
- `01XX Q8`
- `03XX Q4`
- `03XX Q8`
- varied-set `01XX V4`
- varied-set `01XX V8`
- varied-set `03XX V4`
- varied-set `03XX V8`

### Strong-case guardrails
- `02XX Q2`
- `02XX Q4`
- `02XX Q7`
- `05XX Q2`
- `05XX Q4`
- `05XX Q8`

### Minimum bar
Keep the new chunker only if:
- weak non-formal rows become clearly cleaner or more accurate
- and strong formal rows do not materially regress

If results are mixed or ambiguous:
- reject the change

## Evaluation sequence

### Step 1: Freeze baseline
Before touching chunking:
- keep current retrieval code frozen
- keep current generation prompt baseline frozen
- record the baseline retrieval export paths

### Step 2: Implement Variant A only
Change:
- non-formal grouped section split only

Do not change:
- formal contract splitting
- summary injection
- reranker
- embedding model
- anchor gating
- generation prompt

### Step 3: Full reindex
Required because chunk boundaries change.

Actions:
1. rebuild chunk indexes
2. rebuild embeddings
3. refresh Qdrant points

### Step 4: Retrieval-only regression first
Run:
- original retrieval set
- varied retrieval set

Do **not** run generation first.

### Step 5: Compare only retrieval outputs
Judge:
- top citation quality
- fallback cleanliness
- confidence behavior
- whether weak rows improve
- whether formal rows regress

### Step 6: Only if retrieval is clearly better, run generation
If retrieval-only results do not clearly improve:
- stop the experiment
- do not continue into generation

## Metrics to watch

### Good signals
- `01XX/03XX` weak legal-style queries return cleaner summary/section evidence
- less noisy technical-section drift
- fewer irrelevant chunk repetitions
- stronger exact semantic alignment on paraphrases

### Bad signals
- formal-contract clause retrieval becomes less precise
- payment clauses become mixed with generic overview chunks
- summary injection starts compensating for worse base chunking
- chunk counts explode and reranker candidate quality falls

## What not to change during the experiment

Do not change at the same time:
- query embedding instructions
- reranker model
- embedding model
- anchor gating logic
- tail filtering
- generation prompt

One variable only:
- chunk splitting policy

## Recommended initial decision

When this experiment is resumed later:
- start with **Variant A**
- do not test full generic recursive chunking first

## Decision rule

If Variant A:
- improves `01XX/03XX` weak rows
- preserves `02XX/05XX` strong rows

then consider keeping it.

If it only shifts noise around or damages formal retrieval:
- reject it
- keep the current structure-aware splitter
