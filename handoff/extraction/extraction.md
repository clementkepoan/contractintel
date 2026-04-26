# Extraction Handoff

## Scope

This document is a detailed handoff for the current document extraction pipeline only.

It covers:

- how extraction currently works end to end
- what architectural changes have already been applied
- what document classes are now handled correctly
- what is still brittle or incomplete
- how the wiki and stored artifacts relate to extraction output
- what to watch when extending the system

This is not a frontend handoff and not a general repository overview. It is specifically about ingestion, extraction, normalization, validation, persistence, and wiki artifact generation.

## Current Extraction Architecture

The intended architecture is now:

1. document load and blockization
2. regex locator / heuristic extractor
3. optional local LLM normalization
4. deterministic validation
5. persistence into SQLite + raw JSON
6. wiki regeneration from canonical extracted output

The key design decision is:

- regex is still heavily used, but it should primarily answer `where is the evidence?`
- the LLM should answer `what does this evidence mean?`
- deterministic code should answer `is the extracted structure internally coherent?`

This is materially better than the old direction where regex kept expanding into a semantic rulebook.

## Files That Matter

### Loader / ingestion

- [backend/pipeline/ingestion.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/ingestion.py)

Responsible for:

- `.doc` to `.docx` conversion through LibreOffice
- paragraph extraction from DOCX
- table row extraction as synthetic citeable blocks
- lightweight document classification

Important output shape:

- `source_file`
- `working_file`
- `doc_category`
- `paragraphs[]`

Each paragraph-like block contains:

- `paragraph_index`
- `page_estimate`
- `block_id`
- `text`

`block_id` is the key bridge across extraction, citations, retrieval, persistence, and the wiki.

### Core extractor

- [backend/pipeline/extractor.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/extractor.py)

This file currently contains both:

- the regex/heurstic fallback extractor
- the hybrid orchestration entrypoint

Important functions:

- `regex_fallback_extraction(document)`
- `build_locator_blocks(paragraphs)`
- `merge_llm_extraction(...)`
- `extract_contract_data(document)`

### LLM normalization helper

- [backend/pipeline/extractor_llm.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/extractor_llm.py)

Responsible for:

- compacting locator blocks
- compacting regex fallback payload
- building the JSON-only prompt
- parsing and normalizing LLM JSON output

### Validation

- [backend/pipeline/validation.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/validation.py)

This must remain deterministic.

### Persistence / ingest service

- [backend/pipeline/service.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/service.py)

Responsible for:

- ingest idempotency
- versioning
- storing extracted milestones and citations
- writing raw extracted JSON
- triggering wiki regeneration

### Wiki rendering

- [backend/wiki/generator.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/wiki/generator.py)

Responsible for:

- contract pages
- source pages
- milestone pages
- canonical and versioned markdown artifacts

## Extraction Flow In Detail

### 1. Load document

`load_document()` produces a normalized list of blocks from paragraphs and tables.

This was important for `08XX`, because the contract total is expressed through a structured multi-currency table and not only through plain paragraph prose.

### 2. Regex fallback extraction

`regex_fallback_extraction()` is still the baseline extraction path.

It currently extracts:

- contract name
- total amount
- currency
- milestones
- payment type
- progress checkpoints
- retention
- superseded milestone content from deprecated sections
- version metadata
- early validation hints

This fallback is not purely “locator-only” yet. It still contains semantic logic. That is a known architectural compromise.

### 3. Locator block construction

`build_locator_blocks()` now builds richer evidence blocks around important paragraphs instead of only passing the exact matched line.

Each locator block may now include:

- `block_id`
- `paragraph_index`
- `page_estimate`
- `labels`
- `text`
- `context_before`
- `context_after`

This change was applied because the old compact prompt was too thin semantically. It helped avoid the situation where the model only saw a header line without the nearby amount or percentage continuation.

### 4. Hybrid LLM extraction

`extract_contract_data()` now does:

- regex fallback extraction first
- deterministic validation hints on that fallback
- LLM normalization attempt through `extract_contract_with_llm(...)`
- regex return if the LLM path is unavailable or invalid

The LLM path is the intended default architecture, but in practice the real runtime may still fall back often if:

- Ollama is unavailable
- request times out
- model returns invalid JSON

### 5. Merge and canonicalization

`merge_llm_extraction()` rebuilds the final milestone structure and reconstructs citations from `block_id` references.

Important behavior:

- if the LLM returns no result, regex fallback survives
- if the LLM returns field-level evidence block ids, citations are rebuilt from those block ids
- if the LLM provides nothing useful for a milestone, regex fallback content is still used

### 6. Deterministic validation

`validate_contract_data()` runs after extraction and updates:

- `validation[]`
- `validation_status`

This layer currently checks:

- milestone amount sum vs contract total
- milestone percentage sum vs 100
- per-milestone stated `%` vs implied `%`
- declared installment count mismatch
- duplicate milestone order
- missing milestone citations
- missing work items

## Changes Already Applied

### A. Hybrid extractor path exists now

This repo no longer relies only on the original regex path.

The code now contains a real hybrid architecture:

- regex fallback extraction
- locator-block payload
- local LLM normalization
- merge back into canonical output

This was added to address the exact class of semantic failures where regex can locate a clause but still misinterpret what role it plays.

### B. Prompt context was widened

The earlier LLM payload was too narrow and also too aggressively compacted.

Changes applied:

- locator budget increased
- per-block text budget increased
- adjacent context included
- locator block ranking now prefers payment/amount/percentage/milestone evidence instead of blindly taking first N blocks

This was motivated by the observation that failures looked more like timeout / thin context problems than total model incompetence.

### C. Timeout increased

The extraction LLM timeout was increased from 45 seconds to 90 seconds in:

- [backend/pipeline/extractor_llm.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/extractor_llm.py)

This was necessary because Ollama logs showed request cancellation behavior consistent with client timeout, not immediate model crash.

### D. Split-clause stitching was added

The extractor now stitches adjacent milestone/payment lines when a payment sentence is split over multiple DOCX paragraphs.

This directly fixed `05XX`, where:

- first milestone amount was split across two paragraphs
- fourth milestone amount was split across two paragraphs

Without stitching, those fields were rendered as `N/A` or carried broken citations.

### E. Work-item boundary detection was tightened

The extractor used to over-consume downstream generic admin/payment paragraphs and attach them as milestone work items.

That was wrong in:

- `04XX`
- `05XX`

The current logic now tries to stop work-item collection when the following text is clearly:

- invoicing instructions
- payment administration text
- pause-payment / stop-payment conditions

At the same time, it still allows implicit task lists for engineering-node style documents like `08XX`.

### F. Pipeline revisioning was added

The extracted JSON now carries:

- `pipeline_revision`

and ingest no-op behavior in [backend/pipeline/service.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/service.py) was changed so that:

- same source hash + same pipeline revision => true no-op
- same source hash + old pipeline revision => re-extract

This matters because otherwise old ingested contracts would stay stale forever after extractor improvements.

### G. Wiki rendering now prefers canonical raw extraction

The wiki generator now prefers milestone data from the stored raw extracted JSON when available, instead of trusting only the milestone row currently in SQLite.

This was applied because:

- the extractor could be correct
- the rendered wiki could still show stale `N/A`
- the wrong citations could survive in milestone markdown

Current behavior now prefers:

- canonical raw milestone amount
- canonical raw percentage
- canonical raw payment condition
- canonical raw acceptance criteria
- canonical raw milestone citations

## What Is Currently Working

### `02XX`

Status:

- improved versus earlier incorrect retention-heavy interpretation

What was fixed:

- explicit phased installment schedule is preferred over optional guarantee/retention template language
- blank or non-active guarantee text is no longer treated as a live milestone schedule

### `04XX`

Status:

- structurally improved

What now works:

- five milestone payment rows are extracted
- false `work_items[]` on the last milestone were removed
- milestone amounts and percentages remain extracted

What remains real:

- installment count mismatch warning is still valid if the document says six installments but only five are explicitly enumerated
- tiny amount discrepancy on the last milestone still correctly triggers percentage inconsistency

### `05XX`

Status:

- materially improved

What now works:

- all four milestone amounts extract correctly
- first and fourth split-line amounts are stitched
- false work items under the fourth milestone are gone
- milestone pages should now render canonical amounts instead of stale `N/A` after re-ingest

### `06XX`

Status:

- structurally strong

What works:

- four milestones extracted
- each milestone’s explicit `工作項目` list extracted
- payment conditions trimmed cleanly without dragging the work-item block into the terms

What remains:

- validation errors are real source inconsistencies, not parser failures

Specifically:

- total says `8,500,000`
- milestone amounts sum to `8,800,000`
- third and fourth percentages do not match their stated amounts

### `07XX`

Status:

- RFP percentage-only milestone extraction works again after boundary fix

What works:

- `total_amount = None`
- four milestones extracted
- percentages `25 / 30 / 20 / 25`
- completion-condition task items extracted as work items

What this means:

- the extractor now correctly supports percentage-only schedules in pre-award / RFP style docs

### `08XX`

Status:

- strong for both financial structure and engineering-node work-item transfer

What works:

- multi-currency total
- `currency = MULTI`
- NTD/USD breakdown
- four normalized milestones despite mixed milestone naming conventions
- engineering-node task lists transferred into corresponding payment milestones by ordinal position

This is one of the better examples of why ordinal normalization is necessary.

### `09XX`

Status:

- handled as single-payment + retention structure

What works:

- `payment_type = single_with_retention`
- synthetic final payment + retention entries
- retention release timing
- progress checkpoints separated from payment milestones

### `10XX`

Status:

- version conflict behavior is working at the extractor level

What works:

- deprecated content is excluded from active milestone extraction
- superseded milestones are stored separately
- version conflict warning is generated

## What Is Still Not Working Cleanly

### 1. Regex is still doing too much semantic work

Even though the architecture is now hybrid by default, the fallback extractor still owns a lot of semantics:

- payment type inference
- milestone grouping
- acceptance heuristics
- retention construction
- checkpoint interpretation

This is acceptable short term, but it is not the end-state architecture.

The risk:

- every new document edge case will tempt another heuristic branch
- that recreates the same overlapping rulebook problem that motivated the hybrid refactor

### 2. LLM path is still not guaranteed to run in production

The runtime default intends to use the local LLM path, but in practice it may fall back frequently because:

- Ollama is not running
- the model is slow on a specific file
- the prompt still hits latency limits
- the model returns invalid JSON

So the code is architected for hybrid, but the operational quality still depends on local model availability and stability.

### 3. Tests intentionally disable the live LLM

In [tests/test_extractor.py](/Users/mulia/Desktop/Projects/Intern%20Project/tests/test_extractor.py), the standard sample-document tests now monkeypatch the hybrid extractor call to return `None`.

This was done on purpose so tests stay deterministic and do not depend on:

- Ollama availability
- host model state
- timeouts
- nondeterministic JSON structure

This means:

- extractor tests verify the fallback logic and the merge orchestration
- they do not prove live-model quality on your local Ollama instance

There are still explicit hybrid-path tests with monkeypatched LLM responses, but those are structural merge tests, not live inference tests.

### 4. Acceptance criteria vs payment condition is still imperfect

The extractor still sometimes uses the same stitched clause sentence for both:

- `payment_condition`
- `acceptance_criteria`

That is acceptable for some docs, but semantically these are not always the same thing.

Current weak spots:

- payment trigger and acceptance definition are often conflated into one paragraph
- the extractor may copy the entire clause into both fields if it sees `驗收`

This is not a correctness failure for traceability, but it is not ideal field modeling.

### 5. Locator blocks are better, but still paragraph-centric

The locator system is now stronger than before, but it still works at paragraph granularity.

That means:

- if a paragraph contains both meaningful milestone content and admin clutter, the LLM still sees both
- fine-grained clause segmentation has not been implemented

Possible future improvement:

- sub-paragraph spans
- clause-level splitting on punctuation / labels
- explicit `continuation_of` relationships between blocks

### 6. Re-ingest is still required to refresh old wiki artifacts

The code now supports re-extraction on pipeline revision change, but already ingested contracts do not magically update themselves.

To see corrected milestone pages for old data:

- re-upload the original source document
- or write a bulk reprocess command

Until that happens, stale wiki pages may still reflect older extraction logic.

## Known Operational Behavior

### Ollama failure mode observed

Observed earlier:

- `POST /api/generate` returning `500` after about 45 seconds
- Ollama logs showing `context for request finished`

Interpretation:

- likely request timeout / cancellation rather than immediate OOM

What was done:

- extraction timeout raised to 90 seconds
- locator payload widened

What is still true:

- heavy files can still stress local inference
- live production quality depends on local model speed

### Preferred local model assumptions

The system is currently designed around:

- local Ollama
- `qwen2.5:7b`
- `num_ctx = 8192`

That is enough for targeted extraction prompts, but not enough to casually stuff whole documents into the model. The extractor still relies on evidence narrowing first.

## Sample-Document Summary Table

### Good / mostly good

- `05XX`: split milestone amounts fixed, false work items removed
- `06XX`: extraction good, validation catches real source inconsistency
- `07XX`: percentage-only RFP milestones working
- `08XX`: multi-currency + alias normalization + engineering work-item transfer working
- `09XX`: single payment + retention working
- `10XX`: version conflict handling working

### Improved but still semantically debatable

- `02XX`: much better than before, but still a good candidate for live hybrid evaluation because clause semantics are subtle
- `04XX`: false work items fixed, but the source itself still has a declared installment-count ambiguity

## How To Evaluate The Current Extractor

When checking a document, separate these three questions:

### 1. Extraction correctness

Did we identify:

- the right total
- the right milestone count
- the right work-item/task structure
- the right payment/retention model

### 2. Validation correctness

If the source is inconsistent, did we:

- preserve the extracted facts
- raise the right deterministic error

### 3. Rendering correctness

Did the wiki page:

- show the canonical extracted amount
- show milestone-specific citations
- avoid stale DB-only values

This separation matters because some earlier apparent “extractor bugs” were actually wiki rendering drift.

## What To Do Next If Continuing Extraction Work

### High priority

1. Add a bulk reprocess command for all active contracts
2. Run live hybrid extraction on the known hard files with Ollama up
3. Record per-file whether the final result came from:
   - hybrid LLM
   - regex fallback
4. Add extraction telemetry:
   - prompt size
   - LLM response time
   - fallback reason
   - invalid JSON reason

### Medium priority

1. Separate `payment_condition` and `acceptance_criteria` more cleanly
2. Introduce clause-level segmentation instead of raw paragraph-only stitching
3. Reduce semantic responsibility inside regex fallback

### Low priority

1. Add confidence scoring per field, not only per contract
2. Surface extraction-risk vs business-risk separately in the wiki/UI

## Guardrails For Future Changes

Do not:

- keep adding one-off regex branches for every new wording variant
- let validation mutate extracted facts
- let the LLM invent uncited milestone structure
- assume a green test suite means the live Ollama path is healthy

Do:

- keep citations anchored to `block_id`
- prefer explicit clause evidence over generic nearby text
- treat regex as evidence narrowing, not final semantic truth
- keep tests deterministic and separate from live-model smoke tests

## Current Ground Truth

As of this handoff:

- extractor and wiki fixes for `04XX` and `05XX` are implemented
- widened locator context is implemented
- pipeline revision-based re-extraction is implemented
- full test suite passes: `26 passed`

What is still pending operationally:

- re-upload already ingested documents to regenerate stored artifacts under the new extractor revision
- run live Ollama extraction passes on the hardest files to measure real hybrid-path behavior rather than only fallback-path behavior
