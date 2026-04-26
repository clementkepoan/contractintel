# Extraction Fix Plan

## Purpose

This plan tracks the remaining extraction and ingest UX work after the recent hybrid-extraction refactor.

It is intentionally split into:

- `Completed`: already applied in the repo
- `Execute Now`: next implementation batch
- `Later`: useful follow-up, but not required to unblock current extraction reliability

This revision reflects the current codebase state as of the latest extractor fixes and `pipeline_revision` rollout.

## Constraints

Do not:

- change `backend/pipeline/validation.py` logic
- change the database schema
- remove regex fallback
- add cloud APIs
- change the wiki markdown format in a way that breaks existing page structure

Allowed:

- add extraction metadata into stored raw JSON
- add logging / telemetry
- add new modules, CLI commands, and API endpoints
- refactor extractor internals as long as behavior is preserved or improved
- improve frontend upload UX

## Completed

- [x] Hybrid extraction path exists: regex fallback -> locator blocks -> local LLM normalization -> deterministic validation
- [x] Locator blocks now include nearby context instead of only the exact matched paragraph
- [x] LLM extraction timeout increased to 90s
- [x] `pipeline_revision` exists in extracted raw JSON
- [x] Same-hash ingest now reprocesses if stored `pipeline_revision` is older than the current revision
- [x] Split-clause stitching added for multi-paragraph payment clauses
- [x] Work-item boundary logic improved for `04XX` / `05XX`
- [x] `04XX`, `05XX`, `06XX`, `07XX`, `08XX`, `09XX`, `10XX` regression behavior is covered in tests
- [x] Wiki generator now prefers canonical raw extracted milestone fields when available

## Current Gaps

These are still missing or incomplete:

- [ ] no structured extraction telemetry in logs
- [ ] no `_meta` block in extracted raw JSON for extraction-path observability
- [ ] no explicit schema-validation gate for LLM JSON before merge
- [ ] regex path is still not cleanly split into `locator` vs `semantic assembly`
- [ ] `payment_condition` and `acceptance_criteria` are still sometimes too coupled
- [ ] no bulk reprocess CLI/API for already-ingested contracts
- [ ] upload UI still has only a basic `Importing...` state, no progress, no skeleton processing state

## Execute Now

### Phase 1 — Extraction Observability

Goal:

- make every extraction attempt inspectable without opening Python internals

Tasks:

- [ ] add a structured `[EXTRACTION]` log line for every extraction attempt
- [ ] add `_meta` to extracted raw JSON with:
  - `extraction_path`
  - `fallback_reason`
  - `prompt_tokens`
  - `llm_ms`
  - `pipeline_revision`
- [ ] make fallback reasons explicit and stable:
  - `none`
  - `ollama_unavailable`
  - `timeout`
  - `invalid_json`
  - `empty_response`

Notes:

- `pipeline_revision` is already present at top level; `_meta.pipeline_revision` should mirror it
- telemetry must be written before `persist_extracted_json()` so it lands in stored raw JSON

### Phase 2 — LLM Schema Validation

Goal:

- fail closed when Ollama returns malformed or structurally invalid JSON

Tasks:

- [ ] add `validate_llm_response_schema(parsed)` in `backend/pipeline/extractor_llm.py`
- [ ] reject malformed top-level shapes before merge
- [ ] return structured fallback reason `invalid_json` instead of silently merging broken fields

Rules:

- structure validation only
- do not repair malformed payloads beyond existing JSON extraction / fence stripping

### Phase 3 — Regex Refactor Boundary

Goal:

- stop semantic rule-sprawl in `extractor.py`

Target shape:

```python
def build_segment_map(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    ...

def assemble_from_segment_map(segment_map: dict[str, Any], paragraphs: list[dict[str, Any]], source_file: str) -> dict[str, Any]:
    ...
```

Rules for `build_segment_map()`:

- locate evidence
- record block ids / offsets / raw amount strings / raw percentage strings / flags
- no payment-type decision
- no milestone construction
- no retention object construction

Rules for `assemble_from_segment_map()`:

- semantic assembly happens here
- milestone grouping happens here
- retention / payment-type branching happens here
- this becomes the deterministic regex fallback assembler

Important:

- this is a refactor task, not a behavior-change task
- preserve current tested behavior for `04XX` through `10XX`

### Phase 4 — Payment vs Acceptance Separation

Goal:

- reduce field conflation in milestone terms

Tasks:

- [ ] extract `payment_condition` from financial trigger text
- [ ] extract `acceptance_criteria` from completion / test / acceptance text
- [ ] avoid copying the same sentence into both fields unless the source genuinely only gives one mixed sentence

Important:

- this should be done inside the deterministic assembly path, not as a wiki formatting hack

### Phase 5 — Bulk Reprocess

Goal:

- refresh old ingested contracts after extractor improvements without manual re-upload

Deliverables:

- [ ] CLI:
  - `python -m backend.pipeline.reprocess --all`
  - `python -m backend.pipeline.reprocess --file "06XX專案.docx"`
  - `python -m backend.pipeline.reprocess --since-revision <revision>`
- [ ] API:
  - `POST /api/admin/reprocess`

Behavior:

- re-read stored source file
- run current extraction pipeline
- update stored raw JSON
- replace milestone rows / warnings / citations for that contract version
- regenerate wiki artifacts
- skip contracts already at current revision

### Phase 6 — Upload UX

Goal:

- give visible feedback during upload and extraction

Tasks:

- [ ] replace plain upload call with upload-progress capable request
- [ ] add 3-stage UI:
  - `uploading`
  - `processing`
  - `done/error`
- [ ] show progress bar during upload
- [ ] show skeleton loading while backend extraction is running
- [ ] keep user on overview page with no full reload

Frontend entrypoints:

- `frontend/src/pages/OverviewPage.jsx`
- `frontend/src/api/client.js`

## Recommended Execution Order

1. Phase 1 — telemetry and `_meta`
2. Phase 2 — LLM schema validation
3. Phase 5 — bulk reprocess
4. Phase 3 — regex locator/assembly split
5. Phase 4 — better payment vs acceptance separation
6. Phase 6 — upload UX

Rationale:

- observability first, so later refactors are measurable
- safe schema gate next, so hybrid extraction fails cleanly
- reprocess next, so extractor improvements can be applied to existing data
- deeper refactors only after telemetry exists
- frontend last, because it should not block extractor correctness

## Acceptance Criteria

### Backend

- [ ] every extraction attempt emits one structured `[EXTRACTION]` log line
- [ ] stored raw JSON contains `_meta`
- [ ] invalid LLM JSON falls back cleanly with explicit reason
- [ ] bulk reprocess works for `all` and `single file`
- [ ] no regression in existing extractor tests

### Frontend

- [ ] upload progress percentage shown during transfer
- [ ] indeterminate processing state shown during backend extraction
- [ ] skeleton cards visible during processing
- [ ] clear error state on failure
- [ ] no redirect away from overview page

## Execution Note

The next implementation pass should start with:

- Phase 1
- Phase 2
- Phase 5

Those three give immediate operational value without forcing a large semantic refactor first.
