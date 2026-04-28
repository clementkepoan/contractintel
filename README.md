# Contract Intel Dashboard

Offline engineering contract ingestion, extraction, validation, wiki generation, workflow tracking, hybrid retrieval, and React dashboard.

## Project Status

- Core backend pipeline: done
- Wiki and knowledge graph: done
- Dockerized backend plus frontend: done
- API-backed React UI: done
- Final offline embedding cache verification: pending
- Final demo evidence and submission packaging: pending

Current completion estimate: about 85 percent. The product is functionally complete for the assignment flow, but the last 15 percent is mostly operational validation and deliverable packaging.

## Requirements

- Python 3.11 recommended
- macOS, Linux, or WSL2
- Host-installed OpenAI-compatible local model server for local LLM usage
- Docker for the preferred full-stack runtime
- Node.js 20+ if running the frontend outside Docker

## Local Model Setup

Install and start your OpenAI-compatible local model server on the host machine. If you are using oMLX and it exposes the OpenAI API at `http://127.0.0.1:11434/v1`, point the backend there.

```bash
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export LOCAL_MODEL_API_KEY=1111
export LOCAL_MODEL_NAME=lmstudio-community/Qwen3-4B-Instruct-2507-MLX-5bit
```

The chat model is always hosted by a **host-native local model server**, not inside Docker. The backend defaults to `LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1`. If you run the backend in Docker, the backend container connects outward to the host endpoint at `http://host.docker.internal:11434/v1`.

The backend also sets context length with `LOCAL_MODEL_NUM_CTX=8192`. This is passed to the OpenAI-compatible chat completion request.

This server expects both an API key and an explicit model field.

Configured local model:

- `lmstudio-community/Qwen3-4B-Instruct-2507-MLX-5bit`

Examples:

```bash
export LOCAL_MODEL_NUM_CTX=8192
```

If your server requires an explicit model name, set `LOCAL_MODEL_NAME` before startup:

```bash
export LOCAL_MODEL_API_KEY=1111
export LOCAL_MODEL_NAME=lmstudio-community/Qwen3-4B-Instruct-2507-MLX-5bit
```

For embeddings, the backend uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. In Docker, the embedding weights are stored in the named volume `huggingface-cache` so the backend container keeps its own persistent embedding cache. This does not apply to the chat model, which remains host-native.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Optional local-only dependency if you run the backend outside Docker:

```bash
brew install --cask libreoffice
```

## Run Backend Locally

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/api/health
```

## Run Frontend Locally

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api/*` to `http://localhost:8000`.

## Run With Docker

This project dockerizes the frontend, backend, and Qdrant. The chat model does **not** run inside any project container. The model server stays on the host machine, and the backend container calls the host OpenAI-compatible endpoint. LibreOffice and the embedding cache live inside the backend container.

Start the host model server first:

```bash
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
```

Build and run the full stack:

```bash
docker compose up --build
```

Open:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Fresh Start Reset

If you want to test the full flow from ingestion with an empty local state, reset the repo-backed data and wiki files:

```bash
python scripts/reset_demo_state.py
```

Or use the single command:

```bash
make reset-demo
```

If you also want to clear Docker volumes for Qdrant and the embedding cache:

```bash
docker compose down -v
python scripts/reset_demo_state.py
```

Then restart the stack and ingest documents again from scratch.

One-time embedding model cache inside Docker:

```bash
docker compose run --rm backend python -m backend.pipeline.cache_embedding_model
```

After that, the container keeps the embedding model in the `huggingface-cache` volume and can use hybrid retrieval without re-downloading it.

Qdrant is included in the compose stack and is exposed at:

- REST: `http://localhost:6333`
- Dashboard: `http://localhost:6333/dashboard`
- gRPC: `localhost:6334`

## Verify Retrieval

1. Check backend readiness:

```bash
curl http://localhost:8000/api/health
```

You want:

- `local_model_server_reachable: true`
- `embedding_model_ready: true`
- `qdrant_ready: true`

2. Ingest a contract:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -F "file=@Database/02XX專案.docx"
```

3. Run a query:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"第一期付款條件是什麼？","top_k":3}'
```

4. Inspect the response:

- `retrieval_mode: "bm25_only"` means no embedding model is cached yet
- `retrieval_mode: "hybrid_local"` means embeddings are active but Qdrant is not
- `retrieval_mode: "hybrid_qdrant"` means embeddings and Qdrant are both active

5. Verify Qdrant collection contents:

```bash
curl http://localhost:6333/collections
```

The `contract_chunks` collection should appear after a successful ingest with embeddings enabled.

## Chat Memory

The query endpoint is LangChain-based and persists chat messages in SQLite. The first query creates a session:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"第一期付款條件是什麼？","top_k":3}'
```

Use the returned `chat_session_id` on follow-up questions:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"那第二期呢？","top_k":3,"chat_session_id":"chat_xxxxx"}'
```

Inspect stored chat messages:

```bash
curl http://localhost:8000/api/chat/sessions
curl http://localhost:8000/api/chat/sessions/chat_xxxxx/messages
```

## Ingest Documents

Single file:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -F "file=@Database/02XX專案.docx"
```

Batch ingest from `data/uploads/`:

```bash
python backend/pipeline/batch_ingest.py
```

## Current Backend Features

- `.docx` parsing and `.doc` conversion through LibreOffice inside the backend image
- Contract total and milestone extraction with citations
- Validation warnings for missing totals, missing milestones, amount mismatch, percentage mismatch, installment count mismatch, and missing work items
- Acceptance, payment request, and payment logging APIs
- Generated wiki pages in `wiki/`
- Knowledge graph JSON and SVG endpoints
- Hybrid retrieval path: BM25 plus Qdrant-backed dense retrieval when the embedding model is cached

## API Surface

- `GET /api/health`
- `POST /api/ingest`
- `POST /api/ingest/batch`
- `GET /api/contracts`
- `GET /api/contracts/{id}`
- `GET /api/contracts/{id}/financials`
- `GET /api/contracts/{id}/raw`
- `GET /api/milestones/{id}`
- `GET /api/milestones/{id}/status`
- `POST /api/acceptance`
- `GET /api/acceptance/{milestone_id}`
- `GET /api/workflow/{milestone_id}`
- `POST /api/payment-request`
- `GET /api/payment-request/{id}`
- `POST /api/payment`
- `POST /api/query`
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{chat_session_id}/messages`
- `GET /api/wiki`
- `GET /api/wiki/{path}`
- `GET /api/kg/graph`
- `GET /api/kg/svg`
- `GET /api/kg/svg/{contract_id}`
- `GET /api/kg/query/accepted-not-paid`
- `GET /api/kg/query/high-risk-clauses`
- `GET /api/kg/query/payment-trail/{milestone_id}`

## Architecture Summary

- `backend/pipeline/ingestion.py`: file handling and document normalization
- `backend/pipeline/extractor.py`: regex-first extraction and citation creation
- `backend/pipeline/validation.py`: amount and milestone consistency checks
- `backend/pipeline/indexer.py`: BM25 plus optional embedding retrieval
- `backend/pipeline/qdrant_store.py`: Qdrant collection management and vector search
- `backend/pipeline/langchain_query.py`: prompt assembly, retrieval orchestration, OpenAI-compatible chat call, and chat memory persistence
- `backend/pipeline/llm.py`: local OpenAI-compatible model server client
- `backend/wiki/generator.py`: Markdown wiki generation and version conflict logging
- `backend/kg/graph.py`: graph build and SVG rendering
- `backend/api/`: FastAPI route surface
- `frontend/src/pages/`: React screens for contracts, milestones, workflow, query, wiki, KG, and health
- `frontend/src/components/CitationDrawer.jsx`: shared citation drill-down panel

## Limitations

- `.doc` ingestion works in Docker because LibreOffice is bundled in the backend image; local host runs still require host LibreOffice
- Embedding retrieval requires a one-time model download before fully offline use, even in Docker
- Qdrant only contributes once embeddings are cached and chunks have been re-ingested or re-indexed
- Work item extraction is still conservative and misses some contract-specific lists
- The current query answer generation is lightweight and not yet a full citation-grounded RAG synthesis pipeline
- Final grading still needs screenshots or short video evidence plus a clean end-to-end Docker verification run
