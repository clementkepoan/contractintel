from __future__ import annotations

from functools import lru_cache
from typing import Any

import requests
from langchain_core.embeddings import Embeddings

from backend.config import settings


def _embedding_api_base_url() -> str:
    base = settings.embedding_model_base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _embedding_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.embedding_model_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_model_api_key}"
    return headers


def embeddings_available() -> bool:
    return True


def embedding_model_ready() -> bool:
    try:
        vector = _request_embeddings(["embedding healthcheck"], timeout=2.0)
        return bool(vector and vector[0])
    except requests.RequestException:
        return False
    except RuntimeError:
        return False


def _request_embeddings(texts: list[str], timeout: float = 30.0) -> list[list[float]]:
    if not texts:
        return []
    payload: dict[str, Any] = {"input": texts}
    if settings.embedding_model_name:
        payload["model"] = settings.embedding_model_name
    response = requests.post(
        f"{_embedding_api_base_url()}/embeddings",
        headers=_embedding_headers(),
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
    vectors: list[list[float]] = []
    for item in ordered:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Embedding response missing vector payload.")
        vectors.append([float(value) for value in embedding])
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _request_embeddings(texts)


class OMLXEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return _request_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = _request_embeddings([text])
        return vectors[0] if vectors else []


@lru_cache(maxsize=1)
def get_embedding_adapter() -> Embeddings:
    return OMLXEmbeddings()
