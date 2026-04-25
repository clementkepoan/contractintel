from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

try:
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency at runtime
    snapshot_download = None  # type: ignore[assignment]
    SentenceTransformer = None  # type: ignore[assignment]

from backend.config import settings


def embeddings_available() -> bool:
    return SentenceTransformer is not None


@lru_cache(maxsize=1)
def get_embedding_model() -> Any:
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is not installed.")
    if snapshot_download is None:
        raise RuntimeError("huggingface_hub is not available.")
    previous_offline = os.environ.get("HF_HUB_OFFLINE")
    previous_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        local_path = snapshot_download(settings.embedding_model_name, local_files_only=True)
        return SentenceTransformer(local_path, local_files_only=True)
    finally:
        if previous_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_offline
        if previous_transformers_offline is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = previous_transformers_offline


def embedding_model_ready() -> bool:
    if SentenceTransformer is None or snapshot_download is None:
        return False
    try:
        previous_offline = os.environ.get("HF_HUB_OFFLINE")
        previous_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            snapshot_download(settings.embedding_model_name, local_files_only=True)
        finally:
            if previous_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous_offline
            if previous_transformers_offline is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = previous_transformers_offline
        return True
    except Exception:
        return False


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    if hasattr(vectors, "tolist"):
        return vectors.tolist()
    return [list(vector) for vector in vectors]
