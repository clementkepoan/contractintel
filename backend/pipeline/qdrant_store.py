from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from uuid import NAMESPACE_URL, uuid5

try:
    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qdrant_models
except Exception:  # pragma: no cover - optional at runtime
    Document = None  # type: ignore[assignment]
    HuggingFaceEmbeddings = None  # type: ignore[assignment]
    QdrantVectorStore = None  # type: ignore[assignment]
    QdrantClient = None  # type: ignore[assignment]
    qdrant_models = None  # type: ignore[assignment]

from backend.config import settings
from backend.pipeline.embeddings import embedding_model_ready


def qdrant_available() -> bool:
    return QdrantClient is not None and qdrant_models is not None and QdrantVectorStore is not None


@lru_cache(maxsize=1)
def get_qdrant_client() -> Any:
    if QdrantClient is None:
        raise RuntimeError("qdrant-client is not installed.")
    return QdrantClient(url=settings.qdrant_url, timeout=5.0)


def qdrant_ready() -> bool:
    if not qdrant_available():
        return False
    try:
        get_qdrant_client().get_collections()
        return True
    except Exception:
        return False


def point_id_for_chunk(contract_id: str, chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{contract_id}:{chunk_id}"))


@lru_cache(maxsize=1)
def get_langchain_embeddings() -> Any:
    if HuggingFaceEmbeddings is None:
        raise RuntimeError("langchain-huggingface is not installed.")
    if not embedding_model_ready():
        raise RuntimeError("Embedding model is not cached locally.")
    return HuggingFaceEmbeddings(
        model=settings.embedding_model_name,
        cache_folder=os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.getenv("HF_HOME"),
        model_kwargs={"local_files_only": True},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vector_store() -> Any:
    if QdrantVectorStore is None:
        raise RuntimeError("langchain-qdrant is not installed.")
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection_name,
        embedding=get_langchain_embeddings(),
    )


def ensure_collection(vector_size: int) -> None:
    if not qdrant_ready() or qdrant_models is None:
        return
    client = get_qdrant_client()
    exists = client.collection_exists(settings.qdrant_collection_name)
    if exists:
        return
    client.create_collection(
        collection_name=settings.qdrant_collection_name,
        vectors_config=qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE),
    )


def upsert_contract_chunks(contract_id: str, chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
    if not qdrant_ready() or qdrant_models is None or Document is None or not chunks or not embeddings or not embedding_model_ready():
        return
    ensure_collection(len(embeddings[0]))
    client = get_qdrant_client()
    client.delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[qdrant_models.FieldCondition(key="contract_id", match=qdrant_models.MatchValue(value=contract_id))]
            )
        ),
    )
    documents = []
    ids = []
    for chunk, vector in zip(chunks, embeddings, strict=False):
        ids.append(point_id_for_chunk(contract_id, chunk["chunk_id"]))
        documents.append(
            Document(
                page_content=chunk["text"],
                metadata={
                    "contract_id": contract_id,
                    "chunk_id": chunk["chunk_id"],
                    "para_start": chunk["para_start"],
                    "para_end": chunk["para_end"],
                    "page_estimate": chunk["page_estimate"],
                    "chunk_type": chunk.get("chunk_type"),
                    "clause_label": chunk.get("clause_label"),
                    "structured_kind": chunk.get("structured_kind"),
                    "wiki_source_path": chunk.get("wiki_source_path"),
                    "source_label": chunk.get("source_label"),
                    "block_ids": chunk.get("block_ids", []),
                    "parent_chunk_id": chunk.get("parent_chunk_id"),
                    "clause_family": chunk.get("clause_family", []),
                    "document_type": chunk.get("document_type"),
                    "section_label": chunk.get("section_label"),
                    "section_path": chunk.get("section_path"),
                },
            )
        )
    get_vector_store().add_documents(documents=documents, ids=ids)


def search_contract_chunks(contract_id: str | None, query: str, top_k: int) -> list[dict[str, Any]]:
    if not qdrant_ready() or qdrant_models is None or not embedding_model_ready():
        return []
    query_filter = None
    if contract_id:
        query_filter = qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(key="contract_id", match=qdrant_models.MatchValue(value=contract_id))]
        )
    response = get_vector_store().similarity_search_with_score(query=query, k=top_k, filter=query_filter)
    results = []
    for document, score in response:
        payload = document.metadata or {}
        results.append(
            {
                "chunk_id": payload.get("chunk_id"),
                "text_snippet": document.page_content[:300],
                "para_start": int(payload.get("para_start", 0)),
                "para_end": int(payload.get("para_end", 0)),
                "page_estimate": int(payload.get("page_estimate", 0)),
                "chunk_type": payload.get("chunk_type"),
                "clause_label": payload.get("clause_label"),
                "structured_kind": payload.get("structured_kind"),
                "wiki_source_path": payload.get("wiki_source_path"),
                "source_label": payload.get("source_label"),
                "block_ids": payload.get("block_ids", []),
                "parent_chunk_id": payload.get("parent_chunk_id"),
                "clause_family": payload.get("clause_family", []),
                "document_type": payload.get("document_type"),
                "section_label": payload.get("section_label"),
                "section_path": payload.get("section_path"),
                "retrieval_score": float(score or 0.0),
                "contract_id": payload.get("contract_id"),
            }
        )
    return results
