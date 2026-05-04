# Contract Intel Dashboard

Offline engineering contract intelligence system for the technical assignment.

This project ingests `.doc` / `.docx` engineering contracts and RFP-style documents, extracts milestone and payment structure with citations, validates amount consistency, tracks acceptance-to-payment workflow, and exposes the result through a web UI, wiki, knowledge graph, and natural-language query page.

## Submission Scope

Required assignment scope covered:
- offline document ingestion and processing
- automatic extraction of total amount, milestones, milestone amount / percentage, and work items
- validation warnings for inconsistent amounts or incomplete payment clauses
- workflow UI for acceptance -> payment request -> payment logging
- natural-language query with answer basis / citations
- traceability back to source file and paragraph / block location

Bonus scope also included:
- LLM-generated wiki
- knowledge graph
- wiki x KG navigation
- regression runner for retrieval / answer evaluation

## Offline Guarantee

The system is designed to run without cloud APIs.

Confirmed:
- `.doc` and `.docx` ingestion work in the current pipeline
- document processing, retrieval, embeddings, reranking, and answer generation run through local infrastructure
- no cloud LLM or cloud embedding API is required by the application architecture

Practical note:
- local model weights may require a one-time local download into your own model server/cache before disconnecting from the network
- after those local assets exist, the application flow itself runs offline

## Intended Runtime Model

This repository is **Docker-first for the application stack**.

The intended runtime is:
- `frontend` in Docker
- `backend` in Docker
- `qdrant` in Docker
- **oMLX / local OpenAI-compatible model server on the host machine**

The local model server is not inside the project containers.
The backend container talks to the host model server through `host.docker.internal`.

That is the real operator path this repo is built around.

## oMLX / Local Model Server Setup

The backend expects an OpenAI-compatible local endpoint:
- host runtime: `http://127.0.0.1:11434/v1`
- Docker backend runtime: `http://host.docker.internal:11434/v1`

This matches the defaults in [backend/config.py](backend/config.py).

### Model names currently used

Current defaults in [backend/config.py](backend/config.py):
- extraction / general model: `gemma-4-e2b-it-4bit`
- query model: `Qwen3-4B-Instruct-2507-4bit`
- embedding model: `harrier-oss-v1-0.6b-MLX-8bit`
- reranker model: `Qwen3-Reranker-0.6B-mlx-8Bit`

If you want the greeting / lightweight gate model path available in future work, the current intended gate model name is:
- `Qwen3.5-0.8B-4bit`

### Recommended exported variables

Export these in the shell before starting Docker:

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

If your oMLX setup uses a different local port, API key, or published model names, replace those values.

## Startup Instructions

### 1. Start the host-native oMLX / OpenAI-compatible model server

Make sure the host model server is already running before you start Docker.

### 2. Start the application stack

```bash
docker compose up --build
```

This starts:
- frontend
- backend
- qdrant

Open:
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Repository Structure

```text
backend/                 FastAPI app, extraction, retrieval, validation, wiki, KG
frontend/                React + Vite web app
data/                    runtime DB, extracted JSON, indexes, graph JSON
wiki/                    generated wiki pages
Database/                sample assignment documents
tests/                   automated backend tests
regression_test/         retrieval and generation evaluation outputs
```

## Main Features

### 1. Document Processing Pipeline
- ingest `.doc` and `.docx`
- normalize text and source blocks
- chunk and index documents
- hybrid retrieval with BM25 + vectors + reranker
- extract contract structure into JSON / SQLite / wiki / KG
- preserve citations on extracted fields

### 2. Contract Information Extraction
Minimum structured output includes:
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

### 3. Validation
The system checks for:
- missing total amount
- missing milestones
- milestone amount sum mismatch
- percentage inconsistency
- installment count mismatch
- conflicting or incomplete payment clauses

Warnings are stored and surfaced with traceable evidence.

### 4. Acceptance / Payment Workflow
Each milestone supports:
- acceptance record creation
- payment request creation only after a passed acceptance
- payment logging after request
- real-time financial rollups for:
  - total contract amount
  - requested amount
  - paid amount
  - unpaid amount

### 5. Query Interface
- natural-language contract query page
- streaming answers
- hybrid retrieval over ingested contracts
- evidence attached to each response
- persisted chat/session memory in SQLite

### 6. Wiki and KG Bonus
- markdown wiki pages for contracts, milestones, source versions, and queries
- knowledge graph for contracts, milestones, workflow artifacts, validation warnings, and evidence navigation
- bidirectional flow between operational pages, wiki, and KG

## Main UI Pages

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

### Wiki / KG
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

Batch ingest from runtime upload folder:

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

If you also want to clear Docker volumes:

```bash
docker compose down -v
python scripts/reset_demo_state.py
```

## Tests and Verification

Run automated backend tests:

```bash
pytest -q tests
```

See:
- [BackendTestReport.md](BackendTestReport.md)

Current covered cases include:
- RFP / reference document handling
- standard contract extraction
- inconsistent installment validation
- split-line amount extraction
- workflow rule enforcement
- query chat memory persistence

Regression outputs are also included under `regression_test/`.

## Deliverables Present In This Repo

Included:
- executable source code
- startup instructions
- sample assignment documents in `Database/`
- extracted outputs in `data/extracted/`
- generated wiki pages in `wiki/`
- backend test report in [BackendTestReport.md](BackendTestReport.md)
- UI screenshots / design artifacts in `stitch_contract_intel_dashboard/`

## Known Limitations

Main remaining limitations:
- work item extraction is still conservative for some layouts
- non-formal RFP/spec documents are weaker for semantic retrieval than structured contracts
- answer quality still depends on the local model choice
- first-time local model / embedding cache preparation remains an operator responsibility
- KG clause visualization is still evidence-level rather than a fully normalized legal clause ontology

## Suggested Evaluator Demo Flow

1. Start the host-native oMLX/OpenAI-compatible model server
2. Export the model environment variables
3. Run `docker compose up --build`
4. Ingest `Database/02XX專案.docx` and `Database/04XX專案.docx`
5. Open Contract Overview and inspect totals / warnings
6. Open a milestone and inspect citations
7. Record acceptance, request payment, and log payment
8. Ask a natural-language query in Contract Query
9. Open the generated wiki note
10. Open the knowledge graph and inspect workflow / warning relationships

## Summary

This submission meets the assignment’s core requirements and also includes the bonus wiki and KG layers.
The intended operating model is Docker-first with a host-native oMLX/OpenAI-compatible local model server.
