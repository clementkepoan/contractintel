from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.pipeline.embeddings import embed_texts, embedding_model_ready
from backend.pipeline.qdrant_store import qdrant_ready, search_contract_chunks, upsert_contract_chunks


def build_chunks(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for block in extracted.get("blocks", []):
        chunks.append(
            {
                "chunk_id": block["block_id"],
                "text": block["text"],
                "para_start": block["para_start"],
                "para_end": block["para_end"],
                "page_estimate": block["page_estimate"],
            }
        )
    return chunks


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    if " " in text:
        return [token for token in text.split() if token]
    return [char for char in text if not char.isspace()]


def write_chunk_index(contract_id: str, extracted: dict[str, Any]) -> Path:
    chunks = build_chunks(extracted)
    tokenized = [tokenize(chunk["text"]) for chunk in chunks]
    bm25 = BM25Okapi(tokenized) if tokenized else None
    index_payload: dict[str, Any] = {
        "contract_id": contract_id,
        "chunks": chunks,
        "tokenized_chunks": tokenized,
        "embedding_model": settings.embedding_model_name if embedding_model_ready() else None,
    }
    if bm25:
        index_payload["bm25_idf"] = bm25.idf
    if chunks and embedding_model_ready():
        embeddings = embed_texts([chunk["text"] for chunk in chunks])
        index_payload["embeddings"] = embeddings
        if qdrant_ready():
            upsert_contract_chunks(contract_id, chunks, embeddings)
    target = settings.indexes_dir / f"{contract_id}_chunks.json"
    target.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_chunk_index(contract_id: str) -> dict[str, Any] | None:
    path = settings.indexes_dir / f"{contract_id}_chunks.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def search_chunks(contract_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    return hybrid_search_chunks(contract_id, query, top_k)


def cosine_similarity(query_vector: list[float], chunk_vector: list[float]) -> float:
    return float(sum(left * right for left, right in zip(query_vector, chunk_vector, strict=False)))


def reciprocal_rank_fusion(rankings: list[list[tuple[str, float]]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, (chunk_id, _score) in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + (1.0 / (k + position))
    return fused


def vector_search(index_payload: dict[str, Any], query: str, top_k: int) -> list[tuple[str, float]]:
    chunks = index_payload.get("chunks", [])
    embeddings = index_payload.get("embeddings")
    if not chunks or not embeddings or not embedding_model_ready():
        return []
    query_vector = embed_texts([query])[0]
    scored = []
    for chunk, vector in zip(chunks, embeddings, strict=False):
        scored.append((chunk["chunk_id"], cosine_similarity(query_vector, vector)))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]


def qdrant_vector_search(contract_id: str, query: str, top_k: int) -> list[tuple[str, float]]:
    if not embedding_model_ready() or not qdrant_ready():
        return []
    results = search_contract_chunks(contract_id, query, top_k)
    return [(item["chunk_id"], item["retrieval_score"]) for item in results if item.get("chunk_id")]


def hybrid_search_chunks(contract_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    index_payload = load_chunk_index(contract_id)
    if not index_payload:
        return []
    chunks = index_payload.get("chunks", [])
    if not chunks:
        return []
    documents = [
        Document(
            page_content=chunk["text"],
            metadata={
                "chunk_id": chunk["chunk_id"],
                "para_start": chunk["para_start"],
                "para_end": chunk["para_end"],
                "page_estimate": chunk["page_estimate"],
            },
        )
        for chunk in chunks
    ]
    bm25 = BM25Retriever.from_documents(documents, preprocess_func=tokenize, k=top_k)
    bm25_docs = bm25.invoke(query)
    bm25_pairs = [(document.metadata["chunk_id"], 1.0 / rank) for rank, document in enumerate(bm25_docs, start=1)]
    vector_pairs = qdrant_vector_search(contract_id, query, top_k)
    if not vector_pairs:
        vector_pairs = vector_search(index_payload, query, top_k)
    fused = reciprocal_rank_fusion([bm25_pairs, vector_pairs] if vector_pairs else [bm25_pairs])
    chunk_map = {chunk["chunk_id"]: chunk for chunk in chunks}
    results: list[dict[str, Any]] = []
    ranked_chunk_ids = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    bm25_score_map = dict(bm25_pairs)
    vector_score_map = dict(vector_pairs)
    for rank, (chunk_id, score) in enumerate(ranked_chunk_ids, start=1):
        chunk = chunk_map[chunk_id]
        results.append(
            {
                "rank": rank,
                "chunk_id": chunk["chunk_id"],
                "text_snippet": chunk["text"][:300],
                "para_start": chunk["para_start"],
                "para_end": chunk["para_end"],
                "page_estimate": chunk["page_estimate"],
                "retrieval_score": float(score),
                "bm25_score": float(bm25_score_map.get(chunk_id, 0.0)),
                "vector_score": float(vector_score_map.get(chunk_id, 0.0)),
                "retrieval_method": "hybrid_qdrant" if qdrant_ready() and vector_pairs else ("hybrid_local" if vector_pairs else "bm25"),
            }
        )
    return results
