from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    project_root: Path = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parent.parent))
    data_dir: Path = Path(os.getenv("DATA_DIR", project_root / "data"))
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", data_dir / "uploads"))
    extracted_dir: Path = Path(os.getenv("EXTRACTED_DIR", data_dir / "extracted"))
    indexes_dir: Path = Path(os.getenv("INDEXES_DIR", data_dir / "indexes"))
    wiki_dir: Path = Path(os.getenv("WIKI_DIR", project_root / "wiki"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", data_dir / "db.sqlite"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    default_currency: str = os.getenv("DEFAULT_CURRENCY", "TWD")
    local_model_name: str = os.getenv("LOCAL_MODEL_NAME", "qwen2.5:7b")
    local_model_base_url: str = os.getenv("LOCAL_MODEL_BASE_URL", "http://localhost:11434")
    local_model_num_ctx: int = int(os.getenv("LOCAL_MODEL_NUM_CTX", "8192"))
    embedding_model_name: str = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    qdrant_url: str = os.getenv("QDRANT_URL", "http://qdrant:6333")
    qdrant_collection_name: str = os.getenv("QDRANT_COLLECTION_NAME", "contract_chunks")


settings = Settings()


def ensure_runtime_dirs() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.extracted_dir.mkdir(parents=True, exist_ok=True)
    settings.indexes_dir.mkdir(parents=True, exist_ok=True)
    settings.wiki_dir.mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "contracts").mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "contract_versions").mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "sources").mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "milestones").mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "milestone_versions").mkdir(parents=True, exist_ok=True)
    (settings.wiki_dir / "queries").mkdir(parents=True, exist_ok=True)
