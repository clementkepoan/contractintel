from __future__ import annotations

from typing import Any
import logging

import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def _api_base_url() -> str:
    base = settings.reranker_model_base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.reranker_model_api_key:
        headers["Authorization"] = f"Bearer {settings.reranker_model_api_key}"
    return headers


def _normalize_score_map(items: list[tuple[int, float]]) -> dict[int, float]:
    if not items:
        return {}
    values = [score for _index, score in items]
    max_value = max(values)
    min_value = min(values)
    if max_value == min_value:
        return {index: 1.0 for index, _score in items}
    return {index: (float(score) - min_value) / (max_value - min_value) for index, score in items}


def rerank_documents(query: str, documents: list[str], top_n: int | None = None, timeout: float = 20.0) -> list[dict[str, Any]]:
    if not query or not documents or not settings.reranker_model_name:
        return []
    payload: dict[str, Any] = {
        "model": settings.reranker_model_name,
        "query": query,
        "documents": documents,
    }
    if top_n is not None:
        payload["top_n"] = int(top_n)
    try:
        response = requests.post(
            f"{_api_base_url()}/rerank",
            headers=_request_headers(),
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("Reranker request transport failure on /rerank: %s", exc)
        return []
    if not response.ok:
        logger.warning(
            "Reranker request failed on /rerank: model=%s status=%s body=%s",
            settings.reranker_model_name,
            response.status_code,
            response.text[:500],
        )
        return []
    logger.info("Reranker request succeeded on /rerank with model=%s docs=%s", settings.reranker_model_name, len(documents))
    data = response.json()

    raw_items = data.get("results") or data.get("data") or []
    reranked: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            continue
        score = item.get("relevance_score", item.get("score", item.get("relevance")))
        try:
            numeric_score = float(score)
        except (TypeError, ValueError):
            continue
        reranked.append({"index": index, "score": numeric_score})
    reranked.sort(key=lambda item: item["score"], reverse=True)
    return reranked


def rerank_citations(query: str, citations: list[dict[str, Any]], top_n: int | None = None, timeout: float = 20.0) -> list[dict[str, Any]]:
    if not citations:
        return []
    documents: list[str] = []
    for item in citations:
        label = str(item.get("clause_label") or item.get("section_label") or item.get("source_label") or "")
        text = str(item.get("text_snippet") or "")
        if label and text:
            documents.append(f"{label}\n{text}")
        else:
            documents.append(text or label)
    reranked = rerank_documents(query=query, documents=documents, top_n=top_n, timeout=timeout)
    if not reranked:
        return []

    score_pairs = [(entry["index"], entry["score"]) for entry in reranked]
    rerank_norm = _normalize_score_map(score_pairs)
    base_pairs = [(index, float(item.get("retrieval_score", 0.0))) for index, item in enumerate(citations)]
    base_norm = _normalize_score_map(base_pairs)

    updated: list[dict[str, Any]] = []
    for rank, entry in enumerate(reranked, start=1):
        index = entry["index"]
        if index < 0 or index >= len(citations):
            continue
        item = dict(citations[index])
        item["base_retrieval_score"] = float(item.get("retrieval_score", 0.0))
        item["rerank_score"] = float(entry["score"])
        item["rerank_rank"] = rank
        item["retrieval_score"] = (0.7 * rerank_norm.get(index, 0.0)) + (0.3 * base_norm.get(index, 0.0))
        updated.append(item)
    return updated
