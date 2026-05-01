from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return int(cleaned)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return float(cleaned)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _default_local_model_base_url() -> str:
    if _running_in_docker():
        return "http://host.docker.internal:11434/v1"
    return "http://127.0.0.1:11434/v1"


def _default_qdrant_url() -> str:
    if _running_in_docker():
        return "http://qdrant:6333"
    return "http://127.0.0.1:6333"


class Settings(BaseModel):
    project_root: Path = Path(_env_str("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent)))
    data_dir: Path = Path(_env_str("DATA_DIR", str(project_root / "data")))
    uploads_dir: Path = Path(_env_str("UPLOADS_DIR", str(data_dir / "uploads")))
    extracted_dir: Path = Path(_env_str("EXTRACTED_DIR", str(data_dir / "extracted")))
    indexes_dir: Path = Path(_env_str("INDEXES_DIR", str(data_dir / "indexes")))
    wiki_dir: Path = Path(_env_str("WIKI_DIR", str(project_root / "wiki")))
    database_path: Path = Path(_env_str("DATABASE_PATH", str(data_dir / "db.sqlite")))
    chunk_size: int = _env_int("CHUNK_SIZE", 800)
    chunk_overlap: int = _env_int("CHUNK_OVERLAP", 100)
    default_currency: str = _env_str("DEFAULT_CURRENCY", "TWD")
    local_model_name: str = _env_str("LOCAL_MODEL_NAME", "gemma-4-e2b-it-4bit")
    local_query_model_name: str = _env_str("LOCAL_QUERY_MODEL_NAME", "Qwen3-4B-Instruct-2507-4bit")
    local_model_base_url: str = _env_str("LOCAL_MODEL_BASE_URL", _default_local_model_base_url())
    local_model_api_key: str = _env_str("LOCAL_MODEL_API_KEY", "1111")
    local_model_num_ctx: int = _env_int("LOCAL_MODEL_NUM_CTX", 8192)
    local_model_enable_thinking: bool = _env_bool("LOCAL_MODEL_ENABLE_THINKING", False)
    local_model_temperature: float = _env_float("LOCAL_MODEL_TEMPERATURE", 1.0)
    local_model_top_p: float = _env_float("LOCAL_MODEL_TOP_P", 0.95)
    local_model_top_k: int = _env_int("LOCAL_MODEL_TOP_K", 20)
    local_model_min_p: float = _env_float("LOCAL_MODEL_MIN_P", 0.0)
    local_model_presence_penalty: float = _env_float("LOCAL_MODEL_PRESENCE_PENALTY", 1.5)
    local_model_repetition_penalty: float = _env_float("LOCAL_MODEL_REPETITION_PENALTY", 1.0)
    local_model_frequency_penalty: float = _env_float("LOCAL_MODEL_FREQUENCY_PENALTY", 0.0)
    embedding_model_name: str = _env_str("EMBEDDING_MODEL_NAME", "harrier-oss-v1-0.6b-MLX-8bit")
    embedding_model_base_url: str = _env_str("EMBEDDING_MODEL_BASE_URL", _env_str("LOCAL_MODEL_BASE_URL", _default_local_model_base_url()))
    embedding_model_api_key: str = _env_str("EMBEDDING_MODEL_API_KEY", _env_str("LOCAL_MODEL_API_KEY", "1111"))
    reranker_model_name: str = _env_str("RERANKER_MODEL_NAME", "Qwen3-Reranker-0.6B-mlx-8Bit")
    reranker_model_base_url: str = _env_str("RERANKER_MODEL_BASE_URL", _env_str("LOCAL_MODEL_BASE_URL", _default_local_model_base_url()))
    reranker_model_api_key: str = _env_str("RERANKER_MODEL_API_KEY", _env_str("LOCAL_MODEL_API_KEY", "1111"))
    qdrant_url: str = _env_str("QDRANT_URL", _default_qdrant_url())
    qdrant_collection_name: str = _env_str("QDRANT_COLLECTION_NAME", "contract_chunks")


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
