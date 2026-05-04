# Contract Intel Dashboard

Offline contract intelligence platform for engineering contracts and RFP-style documents.

The system ingests `.doc` and `.docx` files, extracts contract structure with citations, validates amount consistency, tracks acceptance and payment workflow state, and exposes the result through a web UI, natural-language query, wiki pages, and a knowledge graph.

## Project Scope

Implemented capabilities:

- offline document ingestion and processing
- automatic extraction of total amount, milestones, milestone amount / percentage, work items, acceptance criteria, and payment conditions
- validation warnings for inconsistent amounts, missing fields, or conflicting clauses
- acceptance -> payment request -> payment logging workflow
- natural-language query with traceable answer basis
- generated wiki pages for contracts, milestones, sources, and queries
- knowledge graph navigation for contracts, milestones, work items, invoices, payments, clauses, and validation warnings
- regression runner for retrieval and generation evaluation

This repository is structured as a Docker-first application stack with local model execution on the host machine.

## Runtime Architecture

The system is designed around three layers:

1. `frontend` in Docker
2. `backend` in Docker
3. `qdrant` in Docker

Local models run outside the containers through an OpenAI-compatible host endpoint, such as a local oMLX deployment.
The backend container talks to that host service through `host.docker.internal`.

That is the intended production and demo setup for this project.

## Local Model Configuration

Current defaults live in [backend/config.py](backend/config.py):

- extraction / general model: `gemma-4-e2b-it-4bit`
- query model: `Qwen3-4B-Instruct-2507-4bit`
- gate model: `Qwen3.5-0.8B-4bit`
- embedding model: `harrier-oss-v1-0.6b-MLX-8bit`
- reranker model: `Qwen3-Reranker-0.6B-mlx-8Bit`

The backend expects an OpenAI-compatible local endpoint.

Default base URLs:

- host: `http://127.0.0.1:11434/v1`
- docker backend: `http://host.docker.internal:11434/v1`

If your local server uses different model names or ports, override them with environment variables before starting the stack.

## Getting Started

### 1. Start the local model server

Start your host-native OpenAI-compatible model server first.

The application expects the local model service to be reachable before the backend begins handling requests.

### 2. Export runtime variables

```bash
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export LOCAL_MODEL_API_KEY=1111

export LOCAL_MODEL_NAME=gemma-4-e2b-it-4bit
export LOCAL_QUERY_MODEL_NAME=Qwen3-4B-Instruct-2507-4bit
export LOCAL_GATE_MODEL_NAME=Qwen3.5-0.8B-4bit

export EMBEDDING_MODEL_NAME=harrier-oss-v1-0.6b-MLX-8bit
export EMBEDDING_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export EMBEDDING_MODEL_API_KEY=1111

export RERANKER_MODEL_NAME=Qwen3-Reranker-0.6B-mlx-8Bit
export RERANKER_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export RERANKER_MODEL_API_KEY=1111
```

### 3. Start the full application stack

```bash
docker compose up --build
```

Services exposed by the stack:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Repository Layout

```text
backend/                 FastAPI app, extraction, retrieval, validation, wiki, KG
frontend/                React + Vite web app
data/                    runtime DB, extracted JSON, indexes, graph JSON
wiki/                    generated wiki pages
Database/                sample assignment documents
regression_test/         retrieval and generation evaluation outputs
tests/                   automated backend tests
plans/                   design and implementation plans
handoff/                 implementation handoff notes
```

## Main Features

### Document Processing

- ingest `.doc` and `.docx`
- normalize source text and block structure
- chunk documents and build indexes
- run hybrid retrieval with BM25, vector search, and reranking
- extract contract structure into JSON, SQLite, wiki pages, and KG nodes
- preserve citations on extracted fields and validation outputs

### Contract Extraction

Minimum structured output:

- `contract_name`
- `total_amount`
- `currency`
- `milestones[]`
- `milestone_id`
- `name`
- `amount`
- `percentage`
- `work_items[]`
- `acceptance_criteria`
- `payment_condition`
- `status`
- `citations[]`
- `validation[]`

### Validation

The pipeline checks for:

- missing total amount
- missing milestones
- milestone amount sum mismatch
- percentage inconsistency
- installment count mismatch
- conflicting or incomplete payment clauses

Validation warnings are stored with traceable source evidence and surfaced in the UI, wiki, and KG.

### Acceptance and Payment Workflow

Each milestone supports:

- acceptance record creation
- payment request creation after acceptance passes
- payment logging after a request exists
- live rollups for:
  - total contract amount
  - payment requested
  - paid
  - unpaid

### Query

The contract query page supports:

- natural-language prompts over the imported contracts
- streaming responses
- traceable evidence snippets
- session persistence in SQLite
- a lightweight gate model for non-contract prompts
- direct injection of live payment workflow state so paid / requested / unpaid status stays queryable without VDB lookups

### Wiki and Knowledge Graph

The generated wiki and KG currently cover:

- contracts
- milestone pages
- source document pages
- query pages
- workflow artifacts
- validation warnings
- evidence navigation

The KG is used as a navigation layer for contracts, milestones, work items, payments, invoices, clauses, and risk or warning relationships.

## UI Pages

- Contract Overview
- Contract Detail
- Milestone Detail
- Payment Workflow
- Contract Query
- Wiki
- Knowledge Graph
- Regression Runner

## Core API Endpoints

### Contracts and milestones

- `GET /api/contracts`
- `GET /api/contracts/{id}`
- `GET /api/contracts/{id}/financials`
- `GET /api/contracts/{id}/raw`
- `GET /api/milestones/{id}`
- `GET /api/milestones/{id}/status`

### Workflow

- `POST /api/acceptance`
- `GET /api/workflow/{milestone_id}`
- `POST /api/payment-request`
- `POST /api/payment`

### Query

- `POST /api/query`
- `POST /api/query/stream`
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{chat_session_id}/messages`
- `GET /api/chat/sessions/{chat_session_id}/turns`

### Wiki and KG

- `GET /api/wiki`
- `GET /api/wiki/page/{path}`
- `GET /api/kg/graph`
- `GET /api/kg/query/accepted-not-paid`
- `GET /api/kg/query/high-risk-warnings`
- `GET /api/kg/query/payment-trail/{milestone_id}`

## Import Example Data

Single ingest:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -F "file=@Database/02XX專案.docx"
```

Batch ingest from the runtime upload folder:

```bash
python backend/pipeline/batch_ingest.py
```

## Reset Runtime State

Reset repo-backed runtime state:

```bash
python scripts/reset_demo_state.py
```

or:

```bash
make reset-demo
```

To clear Docker volumes as well:

```bash
docker compose down -v
```

## Tests and Verification

Run backend tests:

```bash
pytest -q tests
```

Reference test report:

- [BackendTestReport.md](BackendTestReport.md)

Current regression coverage includes:

- RFP / reference document handling
- standard contract extraction
- inconsistent installment validation
- split-line amount extraction
- workflow rule enforcement
- query chat memory persistence

Regression outputs are included under `regression_test/`.

## Current State

The current codebase already includes:

- Docker-first runtime wiring
- offline document processing
- extraction and validation with citations
- workflow tracking for acceptance and payment
- query gating for lightweight non-contract prompts
- live payment context injection into query prompts
- wiki generation
- KG rendering and navigation
- regression runs for retrieval and generation experiments

## Notes

- `.doc` and `.docx` ingestion is supported in the current pipeline.
- The application can run fully offline after local model assets are available on the host machine.
- Runtime outputs such as `data/`, `wiki/`, and regression artifacts are generated during use and are intentionally treated as working data.
