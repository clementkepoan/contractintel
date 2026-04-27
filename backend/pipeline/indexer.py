from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.pipeline.embeddings import embed_texts, embedding_model_ready
from backend.pipeline.qdrant_store import qdrant_ready, search_contract_chunks, upsert_contract_chunks

CLAUSE_HEADER_RE = re.compile(r"^第[一二三四五六七八九十百千\d]+條")
MILESTONE_HEADER_RE = re.compile(
    r"(?:第[一二三四五六七八九十\d]+期|里程碑[一二三四五六七八九十A-Z\d]+|工程節點[一二三四五六七八九十\d]+|階段[一二三四五六七八九十\d]+)"
)
SUBCLAUSE_SIGNAL_RE = re.compile(r"(?:給付|付款|請款|驗收|違約|違約金|扣罰|保固|保證金|固定總價|追加工程款)")
ACTION_SIGNAL_RE = re.compile(r"(?:得|暫停付款|違約金|扣罰|終止|解除|另覓廠商|書面通知|不補償|費用由乙方負擔)")
HEADING_RE = re.compile(r"^##\s+")
LOW_SIGNAL_WIKI_HEADINGS = {
    "overview",
    "metadata",
    "version notes",
    "source timeline",
    "context",
    "related pages",
    "page metadata",
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    normalized = normalize_space(text).lower()
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{1,4}|[%％]+", normalized)


def split_text_with_overlap(text: str, target_size: int, overlap: int) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    if len(normalized) <= target_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    step = max(1, target_size - overlap)
    while start < len(normalized):
        end = min(len(normalized), start + target_size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start += step
    return chunks


def chunk_record(
    *,
    chunk_id: str,
    text: str,
    para_start: int,
    para_end: int,
    page_estimate: int,
    chunk_type: str,
    clause_label: str | None = None,
    structured_kind: str | None = None,
    wiki_source_path: str | None = None,
    source_label: str | None = None,
    block_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "text": normalize_space(text),
        "para_start": para_start,
        "para_end": para_end,
        "page_estimate": page_estimate,
        "chunk_type": chunk_type,
        "clause_label": clause_label,
        "structured_kind": structured_kind,
        "wiki_source_path": wiki_source_path,
        "source_label": source_label,
        "block_ids": block_ids or [],
    }


def build_clause_groups(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in blocks:
        text = normalize_space(block.get("text", ""))
        if not text:
            continue
        is_clause_header = bool(CLAUSE_HEADER_RE.match(text))
        if is_clause_header:
            if current and current["blocks"]:
                groups.append(current)
            current = {"label": text, "blocks": [block]}
            continue
        if current is None:
            current = {"label": None, "blocks": [block]}
        else:
            current["blocks"].append(block)
    if current and current["blocks"]:
        groups.append(current)
    return groups


def build_clause_chunks(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for group_index, group in enumerate(build_clause_groups(extracted.get("blocks", [])), start=1):
        blocks = group["blocks"]
        label = group.get("label") or normalize_space(blocks[0]["text"])[:80]
        merged_text = "\n".join(block["text"] for block in blocks if normalize_space(block.get("text", "")))
        parts = split_text_with_overlap(merged_text, settings.chunk_size, settings.chunk_overlap)
        for part_index, part in enumerate(parts, start=1):
            suffix = f"__part{part_index:02d}" if len(parts) > 1 else ""
            chunks.append(
                chunk_record(
                    chunk_id=f"clause::{group_index:03d}{suffix}",
                    text=part,
                    para_start=int(blocks[0].get("para_start", 0)),
                    para_end=int(blocks[-1].get("para_end", blocks[-1].get("para_start", 0))),
                    page_estimate=int(blocks[0].get("page_estimate", 0)),
                    chunk_type="clause",
                    clause_label=label,
                    source_label=label,
                    block_ids=[str(block.get("block_id")) for block in blocks if block.get("block_id")],
                )
            )
        member_blocks = blocks[1:] if group.get("label") else blocks
        for block_index, block in enumerate(member_blocks, start=1):
            text = normalize_space(block.get("text", ""))
            if not text:
                continue
            if not (MILESTONE_HEADER_RE.search(text) or SUBCLAUSE_SIGNAL_RE.search(text)):
                continue
            block_texts = [text]
            block_ids = [str(block.get("block_id"))] if block.get("block_id") else []
            if block_index < len(member_blocks):
                next_block = member_blocks[block_index]
                next_text = normalize_space(next_block.get("text", ""))
                if next_text and not CLAUSE_HEADER_RE.match(next_text) and not MILESTONE_HEADER_RE.search(next_text):
                    block_texts.append(next_text)
                    if next_block.get("block_id"):
                        block_ids.append(str(next_block.get("block_id")))
            chunks.append(
                chunk_record(
                    chunk_id=f"subclause::{group_index:03d}:{int(block.get('para_start', 0)):04d}",
                    text="\n".join(block_texts),
                    para_start=int(block.get("para_start", 0)),
                    para_end=int(block.get("para_end", block.get("para_start", 0))),
                    page_estimate=int(block.get("page_estimate", 0)),
                    chunk_type="subclause",
                    clause_label=label,
                    source_label=label,
                    block_ids=block_ids,
                )
            )
    return chunks


def summarize_action_sentences(text: str) -> str:
    units = [normalize_space(unit) for unit in re.split(r"[。；\n]+", text) if normalize_space(unit)]
    chosen = [unit for unit in units if ACTION_SIGNAL_RE.search(unit)]
    return "；".join(chosen[:3]) if chosen else normalize_space(text)[:300]


def build_structured_chunks(extracted: dict[str, Any], clause_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    contract_key = extracted.get("contract_key") or "contract"
    currency = extracted.get("currency") or "TWD"
    total_amount = extracted.get("total_amount")
    payment_type = extracted.get("payment_type") or "unknown"
    milestone_count = len(extracted.get("milestones", []))
    summary_text = (
        f"合約摘要：合約名稱 {extracted.get('contract_name') or contract_key}。"
        f"總金額 {total_amount if total_amount is not None else '未明示'} {currency}。"
        f"付款類型 {payment_type}。現有里程碑 {milestone_count} 項。"
    )
    chunks.append(
        chunk_record(
            chunk_id="structured::contract_summary",
            text=summary_text,
            para_start=0,
            para_end=0,
            page_estimate=0,
            chunk_type="structured",
            structured_kind="contract_summary",
            source_label="contract_summary",
        )
    )
    for milestone in extracted.get("milestones", []):
        work_items = "；".join(item for item in milestone.get("work_items", []) if item) or "無明確工作項目"
        chunks.append(
            chunk_record(
                chunk_id=f"struct::milestone::{milestone.get('milestone_key') or milestone.get('source_order')}",
                text=(
                    f"里程碑摘要：{milestone.get('name')}。"
                    f"金額 {milestone.get('amount') if milestone.get('amount') is not None else '未明示'} {currency}。"
                    f"百分比 {milestone.get('percentage') if milestone.get('percentage') is not None else '未明示'}。"
                    f"付款條件：{milestone.get('payment_condition') or '未明示'}。"
                    f"驗收條件：{milestone.get('acceptance_criteria') or '未明示'}。"
                    f"工作項目：{work_items}。"
                ),
                para_start=int(milestone.get("start_paragraph_index", 0) or 0),
                para_end=int(milestone.get("end_paragraph_index", 0) or 0),
                page_estimate=0,
                chunk_type="structured",
                structured_kind="milestone_summary",
                source_label=milestone.get("name"),
                block_ids=[citation.get("block_id") for citation in milestone.get("citations", []) if citation.get("block_id")],
            )
        )
    retention = extracted.get("retention") or {}
    if retention.get("amount") is not None or retention.get("release_condition"):
        chunks.append(
            chunk_record(
                chunk_id="structured::retention",
                text=(
                    f"保留款摘要：金額 {retention.get('amount') if retention.get('amount') is not None else '未明示'} {currency}。"
                    f"比例 {retention.get('percentage') if retention.get('percentage') is not None else '未明示'}。"
                    f"釋放條件：{retention.get('release_condition') or '未明示'}。"
                    f"釋放期限（月）：{retention.get('release_after_months') if retention.get('release_after_months') is not None else '未明示'}。"
                ),
                para_start=0,
                para_end=0,
                page_estimate=0,
                chunk_type="structured",
                structured_kind="retention_summary",
                source_label="retention",
                block_ids=[citation.get("block_id") for citation in retention.get("citations", []) if citation.get("block_id")],
            )
        )
    for index, conflict in enumerate(extracted.get("version_conflicts", []), start=1):
        chunks.append(
            chunk_record(
                chunk_id=f"structured::version_conflict::{index:03d}",
                text=f"版本差異：欄位 {conflict.get('field')} 由 {conflict.get('old')} 變更為 {conflict.get('new')}。",
                para_start=0,
                para_end=0,
                page_estimate=0,
                chunk_type="structured",
                structured_kind="version_conflict_summary",
                source_label="version_conflict",
            )
        )
    for group_index, group in enumerate(clause_groups, start=1):
        blocks = group["blocks"]
        label = group.get("label") or normalize_space(blocks[0]["text"])[:80]
        merged_text = " ".join(normalize_space(block["text"]) for block in blocks if normalize_space(block.get("text", "")))
        if not ACTION_SIGNAL_RE.search(merged_text):
            continue
        chunks.append(
            chunk_record(
                chunk_id=f"structured::action::{group_index:03d}",
                text=f"條款行動摘要：{label}。{summarize_action_sentences(merged_text)}。",
                para_start=int(blocks[0].get("para_start", 0)),
                para_end=int(blocks[-1].get("para_end", blocks[-1].get("para_start", 0))),
                page_estimate=int(blocks[0].get("page_estimate", 0)),
                chunk_type="structured",
                structured_kind="clause_action_summary",
                clause_label=label,
                source_label=label,
                block_ids=[str(block.get("block_id")) for block in blocks if block.get("block_id")],
            )
        )
    return chunks


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + 5 :]


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = "Overview"
    current_lines: list[str] = []
    for line in strip_frontmatter(text).splitlines():
        if HEADING_RE.match(line):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    filtered: list[tuple[str, str]] = []
    for heading, body in sections:
        normalized_heading = normalize_space(heading).lower()
        if normalized_heading in LOW_SIGNAL_WIKI_HEADINGS:
            continue
        if not normalize_space(body):
            continue
        filtered.append((heading, body))
    return filtered


def build_wiki_chunks(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    contract_key = extracted.get("contract_key")
    version_number = extracted.get("version_number")
    if not contract_key or version_number is None:
        return chunks
    candidate_paths = [
        settings.wiki_dir / "contracts" / f"{contract_key}.md",
        settings.wiki_dir / "sources" / f"{contract_key}__v{version_number}.md",
    ]
    candidate_paths.extend(sorted((settings.wiki_dir / "milestones").glob(f"{contract_key}__*.md")))
    for path in candidate_paths:
        if not path.exists():
            continue
        relative = path.relative_to(settings.wiki_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for section_index, (heading, body) in enumerate(split_markdown_sections(text), start=1):
            for part_index, part in enumerate(split_text_with_overlap(body, settings.chunk_size, settings.chunk_overlap), start=1):
                suffix = f"__part{part_index:02d}" if len(body) > settings.chunk_size else ""
                chunks.append(
                    chunk_record(
                        chunk_id=f"wiki::{relative}::{section_index:03d}{suffix}",
                        text=f"{heading}\n{part}",
                        para_start=0,
                        para_end=0,
                        page_estimate=0,
                        chunk_type="wiki",
                        clause_label=heading,
                        wiki_source_path=relative,
                        source_label=relative,
                    )
                )
    return chunks


def build_chunks(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    clause_groups = build_clause_groups(extracted.get("blocks", []))
    chunks = build_clause_chunks(extracted)
    chunks.extend(build_structured_chunks(extracted, clause_groups))
    return [chunk for chunk in chunks if chunk.get("text")]


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
                "chunk_type": chunk.get("chunk_type"),
                "clause_label": chunk.get("clause_label"),
                "structured_kind": chunk.get("structured_kind"),
                "wiki_source_path": chunk.get("wiki_source_path"),
                "source_label": chunk.get("source_label"),
                "block_ids": chunk.get("block_ids", []),
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
                "text_snippet": chunk["text"][:500],
                "para_start": chunk["para_start"],
                "para_end": chunk["para_end"],
                "page_estimate": chunk["page_estimate"],
                "chunk_type": chunk.get("chunk_type"),
                "clause_label": chunk.get("clause_label"),
                "structured_kind": chunk.get("structured_kind"),
                "wiki_source_path": chunk.get("wiki_source_path"),
                "source_label": chunk.get("source_label"),
                "block_ids": chunk.get("block_ids", []),
                "retrieval_score": float(score),
                "bm25_score": float(bm25_score_map.get(chunk_id, 0.0)),
                "vector_score": float(vector_score_map.get(chunk_id, 0.0)),
                "retrieval_method": "hybrid_qdrant" if qdrant_ready() and vector_pairs else ("hybrid_local" if vector_pairs else "bm25"),
            }
        )
    return results
