# Repository Guidelines

## Project Structure & Module Organization

This repository contains the project specification in `ProjectSetup.md` and sample contract files in `Database/`. The documented application layout is:

- `backend/`: FastAPI service, SQLModel models, ingestion pipeline, wiki generator, and knowledge graph modules.
- `frontend/`: React 18 + Vite UI, with pages in `frontend/src/pages/`, components in `frontend/src/components/`, and API wrappers in `frontend/src/api/`.
- `data/`: runtime uploads, SQLite database, extracted JSON, BM25/FAISS indexes, and graph files.
- `wiki/`: generated Markdown pages for contracts, milestones, and ingest logs.
- `tests/`: backend extraction, validation, and integration tests.

Keep source files out of `Database/`; reserve it for `.doc` and `.docx` samples.

## Build, Test, and Development Commands

Use these commands from `ProjectSetup.md` once the scaffold exists:

- `python3 -m venv .venv && source .venv/bin/activate`: create and activate the backend environment.
- `pip install -r requirements.txt`: install backend dependencies.
- `ollama pull qwen3:8b`: download the local host-native LLM; this is the expected network-dependent setup step.
- `uvicorn backend.main:app --port 8000 --reload`: run the FastAPI backend locally.
- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev`: run the Vite development server.
- `cd frontend && npm run build`: build the production frontend.
- `python backend/pipeline/batch_ingest.py`: batch-ingest files placed in `data/uploads/`.

## Coding Style & Naming Conventions

Use Python 3.10+ with 4-space indentation, type hints on public functions, and snake_case module names. Keep backend modules grouped by responsibility: API routes in `backend/api/`, extraction in `backend/pipeline/`, and persistence in `backend/db/`. Use PascalCase for React components and camelCase for JavaScript functions.

## Testing Guidelines

Place tests in `tests/` and name them `test_*.py`. Prioritize deterministic tests for extraction, amount validation, citation mapping, and end-to-end ingestion. Run backend tests with `pytest` once test dependencies are added. For frontend work, add component or integration tests if UI behavior becomes non-trivial.

## Commit & Pull Request Guidelines

This repository has no commits yet, so there is no existing convention. Use concise imperative messages, for example `Add batch ingest pipeline` or `Fix milestone amount validation`. Pull requests should include a summary, test evidence, affected commands, screenshots for UI changes, and notes for model, data, or offline-runtime assumptions.

## Security & Configuration Tips

Preserve the offline-first guarantee. Do not add cloud API calls for document contents. Keep generated data, indexes, local databases, `.venv/`, and frontend build output out of version control unless explicitly required.
