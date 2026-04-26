# Handoff 1

## Project Purpose

This repository implements an offline contract intelligence system for engineering contracts and related documents. It ingests `.doc` / `.docx` files, extracts structured contract data with citations, validates the extracted structure, stores the results in SQLite plus JSON artifacts, builds a markdown wiki and a lightweight knowledge graph, and serves everything through a FastAPI backend and a React frontend.

The system is explicitly designed for offline use:

- local LLM via Ollama
- local embeddings via Hugging Face sentence-transformers
- local vector store via Qdrant
- no cloud LLM or embedding APIs

## Runtime Architecture

The runtime has three main services:

- `backend/`: FastAPI app, extraction pipeline, persistence, wiki generation, knowledge graph generation, and query APIs
- `frontend/`: React + Vite single-page app served as static assets in Docker
- `qdrant/`: vector store for dense retrieval over chunked contract text

Ollama is not containerized in the current preferred setup. It is expected to run on the host machine and is reached through `LOCAL_MODEL_BASE_URL`, defaulting to `http://localhost:11434` locally and `http://host.docker.internal:11434` in Docker.

Core configuration lives in [backend/config.py](</Users/mulia/Desktop/Projects/Intern Project/backend/config.py>). Runtime directories are created during FastAPI startup by `ensure_runtime_dirs()`.

## Backend Entry Point

The API app is defined in [backend/main.py](</Users/mulia/Desktop/Projects/Intern Project/backend/main.py>). On startup it:

- creates runtime folders under `data/` and `wiki/`
- initializes the SQLite schema
- exposes `/api/health` for runtime readiness

Mounted API groups:

- ingest
- contracts
- milestones
- workflow
- query
- wiki
- knowledge graph

`/api/health` reports:

- Ollama reachability
- embedding cache readiness
- Qdrant readiness
- LibreOffice availability for `.doc` conversion

## Persistence Model

The main SQLModel schema is in [backend/db/models.py](</Users/mulia/Desktop/Projects/Intern Project/backend/db/models.py>).

Key tables:

- `Contract`: canonical contract version row, source metadata, extraction method, validation status
- `Milestone`: extracted milestone rows with amount, percentage, work items, payment condition, and citations
- `Citation`: traceability rows for extracted fields, keyed by `block_id`, paragraph indices, and source file
- `ValidationWarning`: deterministic post-extraction findings
- `AcceptanceRecord`, `PaymentRequest`, `Payment`: workflow tracking tables
- `ChatSession`, `ChatMessage`: query chat memory
- `IngestEvent`: ingest/versioning audit log
- `FiledQuery`: wiki-filed natural language query records

This means the repo stores the same knowledge in several layers:

- SQLite for live app state
- `data/extracted/*.json` as raw canonical extraction snapshots
- `data/indexes/*.json` for retrieval chunks
- `wiki/` markdown pages for human-readable persistent knowledge

## Ingestion Flow

The entrypoint is [backend/api/ingest.py](</Users/mulia/Desktop/Projects/Intern Project/backend/api/ingest.py>) which calls `ingest_upload()` in [backend/pipeline/service.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/service.py>).

High-level flow:

1. Persist uploaded file into `data/uploads/`
2. Hash the file for idempotency
3. Resolve `contract_key` from the filename stem
4. If the active version already has the same source hash, treat ingest as `noop`
5. Otherwise load the document, extract structured data, validate it, version it, and persist it
6. Build chunk indexes and update Qdrant if embeddings are available
7. Rebuild wiki artifacts
8. Rebuild the knowledge graph

Versioning logic:

- contracts are versioned per `contract_key`
- older versions are marked `is_superseded = true`
- version diffs are stored in `IngestEvent` and also surfaced into the wiki

## Document Loading And Classification

[backend/pipeline/ingestion.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/ingestion.py>) handles:

- `.doc` to `.docx` conversion via LibreOffice `soffice`
- paragraph extraction
- DOCX table row extraction as synthetic paragraph-like blocks
- lightweight document classification into `contract`, `rfp`, or `construction_instruction`

Every extracted text block gets:

- `paragraph_index`
- estimated page number
- stable `block_id`
- raw text

Those `block_id` values are the key bridge between extraction, citations, retrieval, and wiki traceability.

## Extraction Architecture

The current extractor is centered in [backend/pipeline/extractor.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/extractor.py>) and the local LLM extraction helper in [backend/pipeline/extractor_llm.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/extractor_llm.py>).

Current intended architecture is:

1. Regex locator
2. LLM extractor
3. Deterministic validator
4. Regex fallback if the LLM path is unavailable or invalid

### Regex Locator Responsibilities

Regex is still heavily used, but the architectural intention is that regex should only locate evidence, not own final semantics.

What regex currently does well:

- find total amount clauses
- detect milestone-like headers such as `第X期`, `里程碑`, `工程節點`, `階段X尾款`
- attach adjacent work items
- detect multi-currency table totals
- detect versioned or deprecated sections
- detect single-payment / retention patterns
- detect checkpoints and acceptance-related clauses

### LLM Extractor Responsibilities

`extract_contract_with_llm()` in [backend/pipeline/extractor_llm.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/extractor_llm.py>) is designed to take:

- locator blocks
- regex fallback snapshot
- validation hints

and return canonical JSON:

- `doc_category`
- `payment_type`
- `total_amount`
- `currency`
- milestone list
- retention object
- progress checkpoints

The LLM is instructed to:

- use only provided evidence
- prefer explicit phased payment schedules over optional alternatives
- not treat blank guarantee templates as live retention terms
- return JSON only
- attach evidence through `block_id` lists

### Current Practical State

The codebase now contains the hybrid extraction path and keeps regex as fallback. This is the right architecture for this project, because the documents are semantically inconsistent and pure regex would continue to expand into overlapping special cases.

The main failure case that motivated this shift was `Database/02XX專案.docx`, where a rule-based path incorrectly treated optional retention template clauses as the active schedule instead of the explicit three-phase payment terms.

## Validation Layer

Validation is in [backend/pipeline/validation.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/validation.py>).

This layer is intentionally deterministic and should stay that way.

Current validations include:

- milestone amount sum vs contract total
- milestone percentage sum vs 100
- per-milestone amount vs stated percentage
- declared installment count mismatch
- duplicate milestone ordering
- missing citations
- missing work items

This separation is important:

- extraction decides what the contract says
- validation decides whether the extracted structure is internally coherent

## Retrieval And Query Flow

Retrieval is implemented in [backend/pipeline/indexer.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/indexer.py>), [backend/pipeline/embeddings.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/embeddings.py>), and [backend/pipeline/qdrant_store.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/qdrant_store.py>).

The retrieval stack is:

- BM25 over local chunk JSON
- optional local dense embeddings
- optional Qdrant vector retrieval
- reciprocal rank fusion over sparse and dense results

Natural language query answering is in [backend/pipeline/langchain_query.py](</Users/mulia/Desktop/Projects/Intern Project/backend/pipeline/langchain_query.py>).

Query path:

1. retrieve top-k evidence chunks
2. format evidence with paragraph/page metadata
3. if Ollama is reachable, answer with `ChatOllama`
4. otherwise return an extractive fallback
5. store chat messages in SQLite
6. optionally file the answer into the wiki

## Wiki Layer

Wiki generation is implemented in [backend/wiki/generator.py](</Users/mulia/Desktop/Projects/Intern Project/backend/wiki/generator.py>).

Generated page families:

- `wiki/contracts/`
- `wiki/contract_versions/`
- `wiki/sources/`
- `wiki/milestones/`
- `wiki/milestone_versions/`
- `wiki/queries/`
- root `wiki/index.md`
- root `wiki/log.md`

The wiki is not just export output. It is treated as a maintained persistent knowledge layer. Canonical pages are updated across ingests, version pages are immutable snapshots, and query answers can also be filed as new wiki pages.

There is also an optional local-LLM wiki maintenance pass that revises canonical markdown while preserving frontmatter, links, and contradictions.

## Knowledge Graph

[backend/kg/graph.py](</Users/mulia/Desktop/Projects/Intern Project/backend/kg/graph.py>) builds a local graph JSON from live database state.

Graph nodes include:

- contracts
- milestones
- work items
- invoices / payment requests
- payments
- validation-warning clauses

The graph is currently stored as `data/indexes/graph.json` and can be rendered as SVG through API endpoints.

## Frontend Structure

The frontend shell is in [frontend/src/App.jsx](</Users/mulia/Desktop/Projects/Intern Project/frontend/src/App.jsx>) and [frontend/src/components/Layout.jsx](</Users/mulia/Desktop/Projects/Intern Project/frontend/src/components/Layout.jsx>).

Route model is hash-based and page-local rather than React Router based. Main screens:

- contract overview
- contract detail
- milestone detail
- payment workflow
- contract query
- contract wiki
- knowledge graph
- system health

API bindings are centralized in [frontend/src/api/client.js](</Users/mulia/Desktop/Projects/Intern Project/frontend/src/api/client.js>). It also includes retry behavior for transient `502/503/504` responses during startup.

## Reset And Operational Notes

[scripts/reset_demo_state.py](</Users/mulia/Desktop/Projects/Intern Project/scripts/reset_demo_state.py>) clears:

- uploads
- extracted JSON
- retrieval indexes
- wiki content
- SQLite database

It does not remove Docker volumes unless the operator separately runs `docker compose down -v`.

## Current Design Principles

These are the most important architectural assumptions to preserve:

- offline-only is a hard requirement
- citations are first-class and must survive every extraction path
- SQLite is the operational source of truth; JSON and wiki are derived artifacts
- contract versioning is explicit and must not be overwritten in place
- regex should remain a locator / fallback, not a growing semantic rulebook
- deterministic validation must remain post-extraction and authoritative for math / consistency checks

## Main Risks / Future Work

- The hybrid extractor should continue to shift semantic interpretation away from regex and into the LLM path, while keeping citations strict.
- The `Milestone` SQL schema currently does not explicitly store milestone subtype such as retention vs standard installment; if retention semantics need richer workflow behavior, the DB model may need extension.
- Generated `data/`, `wiki/`, and `__pycache__` artifacts frequently dirty the worktree; contributors should avoid reviewing them as source changes unless the task is specifically about generated output.
