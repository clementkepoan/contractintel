# Backend, Data, Wiki, and Docker Checklist

## Status
- [x] Backend APIs and data pipeline exist.
- [x] SQLite persistence is in place.
- [x] Wiki generation is in place.
- [x] Knowledge graph endpoints are in place.
- [x] Dockerized backend runtime exists.
- [ ] Final offline embedding cache needs a clean end-to-end verification run.
- [ ] Submission artifacts still need final screenshots/video packaging.

## Compliance
- [x] Keep document processing local after setup.
- [x] Use local BM25, embeddings, Ollama, and graph tooling.
- [x] Keep milestone and amount generation tied to document extraction.
- [x] Attach traceable citations to extracted fields.

## Data Pipeline
- [x] Parse `.docx` files with `python-docx`.
- [x] Convert `.doc` files with LibreOffice headless in Docker.
- [x] Normalize paragraphs into blocks with page and source metadata.
- [x] Support contracts, RFPs, and construction instruction variants.
- [x] Accept batch ingest through CLI or API.

## Extraction
- [x] Extract totals, milestones, percentages, payment conditions, and citations.
- [x] Convert Chinese numerals for contract totals.
- [x] Use regex-first extraction with a local LLM fallback path.
- [x] Emit standard JSON after ingest.
- [x] Flag missing or inconsistent values with warnings and source clauses.

## Validation and Workflow
- [x] Validate total amount versus milestone totals.
- [x] Validate percentage consistency.
- [x] Store acceptance records.
- [x] Block payment requests until acceptance passes.
- [x] Store payment requests and payments.
- [x] Calculate total, requested, paid, and unpaid values.

## Retrieval
- [x] Build BM25 indexes.
- [x] Build optional dense embeddings.
- [x] Use Qdrant when embeddings are available.
- [x] Use LangChain-backed query orchestration.
- [x] Persist chat memory in SQLite.

## Wiki
- [x] Generate `wiki/index.md`.
- [x] Generate `wiki/log.md`.
- [x] Generate contract pages.
- [x] Generate milestone pages.
- [x] Detect and log version conflicts.

## Knowledge Graph
- [x] Build contract, milestone, work item, payment, and clause graph data.
- [x] Expose graph JSON.
- [x] Expose SVG graph rendering.
- [x] Add named graph queries.

## Tests
- [x] Extraction tests for real sample files.
- [x] Validation tests for amount mismatches.
- [x] Workflow tests for acceptance and payment blocking.
- [x] Query tests for citations and chat memory.

## Docker
- [x] Backend image includes LibreOffice and Python dependencies.
- [x] Backend container uses host Ollama.
- [x] Compose includes backend and Qdrant.
- [x] HuggingFace cache is mounted for embeddings.

## Remaining
- [ ] Confirm the embedding cache is prewarmed in the exact runtime volume.
- [ ] Capture final demo evidence.
- [ ] Include final example outputs in the submission bundle.
