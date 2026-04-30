from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.api.admin import router as admin_router
from backend.api.contracts import router as contracts_router
from backend.api.ingest import router as ingest_router
from backend.api.kg import router as kg_router
from backend.api.milestones import router as milestones_router
from backend.api.query import router as query_router
from backend.api.wiki import router as wiki_router
from backend.api.workflow import router as workflow_router
from backend.config import ensure_runtime_dirs
from backend.config import settings
from backend.db.database import init_db
from backend.pipeline.embeddings import embedding_model_ready
from backend.pipeline.llm import llm_available
from backend.pipeline.qdrant_store import qdrant_ready
from shutil import which


RESET_MARKER_PATH = Path("data/reset_marker.txt")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_runtime_dirs()
    init_db()
    yield


app = FastAPI(title="Contract RAG Backend", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    reset_marker = None
    if RESET_MARKER_PATH.exists():
        try:
            reset_marker = RESET_MARKER_PATH.read_text(encoding="utf-8").strip() or None
        except Exception:
            reset_marker = None
    return {
        "status": "ok",
        "offline_only": True,
        "local_model_server_reachable": llm_available(),
        "embedding_model_ready": embedding_model_ready(),
        "qdrant_ready": qdrant_ready(),
        "doc_conversion_available": which("soffice") is not None,
        "infrastructure": {
            "local_model_name": settings.local_model_name,
            "local_extraction_model_name": settings.local_model_name,
            "local_query_model_name": settings.local_query_model_name,
            "local_model_base_url": settings.local_model_base_url,
            "local_model_num_ctx": settings.local_model_num_ctx,
            "embedding_model_name": settings.embedding_model_name,
            "embedding_model_base_url": settings.embedding_model_base_url,
            "reranker_model_name": settings.reranker_model_name,
            "qdrant_url": settings.qdrant_url,
            "qdrant_collection_name": settings.qdrant_collection_name,
            "api_docs_path": "/docs",
            "qdrant_dashboard_url": "http://localhost:6333/dashboard",
            "reset_marker": reset_marker,
        },
    }


app.include_router(ingest_router)
app.include_router(admin_router)
app.include_router(contracts_router)
app.include_router(milestones_router)
app.include_router(workflow_router)
app.include_router(query_router)
app.include_router(wiki_router)
app.include_router(kg_router)
