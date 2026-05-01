from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.pipeline.embeddings import embed_query_text, embed_texts, embedding_model_ready
from backend.pipeline.qdrant_store import qdrant_ready, search_contract_chunks, upsert_contract_chunks

logger = logging.getLogger(__name__)

CLAUSE_HEADER_RE = re.compile(r"^第[一二三四五六七八九十百千\d]+條")
MILESTONE_HEADER_RE = re.compile(
    r"(?:第[一二三四五六七八九十\d]+期|里程碑[一二三四五六七八九十A-Z\d]+|工程節點[一二三四五六七八九十\d]+|階段[一二三四五六七八九十\d]+)"
)
SUBCLAUSE_SIGNAL_RE = re.compile(
    r"(?:給付|付款|請款|驗收|違約|違約金|扣罰|保固|保證金|固定總價|追加工程款|不得追加|法令變更|政策變更|不得調整|單價不予調整|情事變更)"
)
ACTION_SIGNAL_RE = re.compile(r"(?:得|暫停付款|違約金|扣罰|終止|解除|另覓廠商|書面通知|不補償|費用由乙方負擔)")
NONFORMAL_SIGNAL_RE = re.compile(r"(?:付款|請款|驗收|保固|安全|規範|功能|要求|不得|應|須|完成|測試|圖說|範圍)")
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
SUMMARY_SECTION_FAMILY_HINTS = {
    "契約目的": [],
    "商務與付款": ["payment", "milestone", "price_adjustment"],
    "交付與驗收": ["acceptance", "warranty"],
    "風險與注意事項": ["damages", "warranty", "price_adjustment", "force_majeure"],
    "At A Glance": [],
    "Milestone And Payment Structure": ["payment", "milestone", "price_adjustment"],
    "Delivery And Acceptance": ["acceptance", "warranty"],
    "Payment Procedures And Commercial Notes": ["payment", "price_adjustment"],
    "Risks And Open Issues": ["damages", "warranty", "price_adjustment", "force_majeure"],
}
NONFORMAL_ALLOWED_FAMILIES = {
    "payment",
    "acceptance",
    "warranty",
    "price_adjustment",
    "force_majeure",
    "damages",
    "milestone",
}
NONFORMAL_SECTION_HINTS = {
    "專案名稱",
    "專案地點",
    "施工名稱",
    "施工地點",
    "施工內容",
    "工程說明",
    "設計原則與內容範圍",
    "耗能管理",
    "界面操作使用規範",
    "智慧辦公室",
    "建築能源管理系統",
    "家庭能源管理系統",
    "資安要求",
    "保固要求",
    "驗收標準",
}

CLAUSE_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payment": ("付款", "給付", "請款", "期款", "發票"),
    "acceptance": ("驗收", "核定", "確認", "測試通過"),
    "penalty": ("違約金", "扣罰", "罰則", "逾期"),
    "termination": ("終止", "解除", "另覓廠商", "收回自辦"),
    "warranty": ("保固", "修補", "換新", "缺失"),
    "retention": ("保留款", "保證金", "保固保證金", "履約保證金"),
    "price_adjustment": ("固定總價", "不得追加", "不得調整", "單價不予調整", "法令變更", "政策變更", "情事變更"),
    "force_majeure": ("不可抗力", "天災", "關稅措施", "情事變更"),
    "subcontracting": ("轉包", "分包", "轉讓"),
    "damages": ("損害賠償", "賠償", "求償", "扣抵"),
    "milestone": ("第一期", "第二期", "第三期", "第四期", "里程碑", "工程節點"),
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    normalized = normalize_space(text).lower()
    primary = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{1,4}|[%％]+", normalized)
    if len(primary) >= 3:
        return primary
    fallback = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized)
    if len(fallback) >= 3:
        return fallback
    compact_cjk = re.sub(r"[^\u4e00-\u9fff]", "", normalized)
    if len(compact_cjk) >= 4:
        bigrams = [compact_cjk[idx : idx + 2] for idx in range(len(compact_cjk) - 1)]
        if bigrams:
            return bigrams
    ascii_words = re.findall(r"[a-z0-9_]+", normalized)
    if ascii_words:
        return ascii_words
    last_resort = [char for char in compact_cjk[:10] if char.strip()]
    return last_resort


def tokenization_stats(contract_id: str, chunks: list[dict[str, Any]], tokenized_chunks: list[list[str]]) -> dict[str, float | int]:
    total = len(tokenized_chunks)
    empty = sum(1 for tokens in tokenized_chunks if len(tokens) == 0)
    avg_len = (sum(len(tokens) for tokens in tokenized_chunks) / total) if total else 0.0
    short = sum(1 for tokens in tokenized_chunks if len(tokens) < 3)
    if empty or avg_len < 3.0 or short > max(3, total // 2):
        sample_text = ""
        for chunk, tokens in zip(chunks, tokenized_chunks, strict=False):
            if len(tokens) == 0:
                sample_text = normalize_space(chunk.get("text", ""))[:80]
                break
        logger.warning(
            "BM25 tokenization sparse for %s: empty=%s/%s short=%s avg_tokens=%.2f sample=%r",
            contract_id,
            empty,
            total,
            short,
            avg_len,
            sample_text,
        )
    return {"total": total, "empty": empty, "short": short, "avg_len": avg_len}


def _retokenize_if_sparse(contract_id: str, chunks: list[dict[str, Any]], tokenized_chunks: list[list[str]]) -> list[list[str]]:
    stats = tokenization_stats(contract_id, chunks, tokenized_chunks)
    total = int(stats["total"])
    if not total:
        return tokenized_chunks
    empty = int(stats["empty"])
    short = int(stats["short"])
    avg_len = float(stats["avg_len"])
    should_refresh = empty > 0 or avg_len < 3.0 or short > max(3, total // 2)
    if not should_refresh:
        return tokenized_chunks
    refreshed = [tokenize(chunk["text"]) for chunk in chunks]
    refreshed_stats = tokenization_stats(contract_id, chunks, refreshed)
    if (
        int(refreshed_stats["empty"]) < empty
        or float(refreshed_stats["avg_len"]) > avg_len
        or int(refreshed_stats["short"]) < short
    ):
        logger.info(
            "BM25 tokenization refreshed for %s: empty %s->%s avg_tokens %.2f->%.2f short %s->%s",
            contract_id,
            empty,
            int(refreshed_stats["empty"]),
            avg_len,
            float(refreshed_stats["avg_len"]),
            short,
            int(refreshed_stats["short"]),
        )
        return refreshed
    return tokenized_chunks


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


def detect_document_type(extracted: dict[str, Any]) -> str:
    category = normalize_space(str(extracted.get("doc_category") or extracted.get("document_type") or "")).lower()
    if category == "contract":
        return "formal_contract"
    if category == "construction_instruction":
        return "instruction_manual"
    if category == "rfp":
        return "spec_rfp"
    return "mixed"


def detect_clause_family(text: str, *, document_type: str = "formal_contract") -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    family_scores: list[tuple[str, int]] = []
    for family, keywords in CLAUSE_FAMILY_KEYWORDS.items():
        count = sum(1 for keyword in keywords if keyword in normalized)
        if count <= 0:
            continue
        family_scores.append((family, count))
    if document_type == "formal_contract":
        return [family for family, _count in family_scores]
    constrained = [(family, count) for family, count in family_scores if family in NONFORMAL_ALLOWED_FAMILIES]
    constrained.sort(key=lambda item: (-item[1], item[0]))
    return [family for family, _count in constrained[:2]]


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
    parent_chunk_id: str | None = None,
    clause_family: list[str] | None = None,
    document_type: str | None = None,
    section_label: str | None = None,
    section_path: str | None = None,
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
        "parent_chunk_id": parent_chunk_id,
        "clause_family": clause_family or [],
        "document_type": document_type,
        "section_label": section_label,
        "section_path": section_path,
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


def strip_section_heading(text: str) -> str:
    return normalize_space(re.sub(r"[:：]\s*$", "", text))


def is_nonformal_heading(text: str, next_text: str) -> bool:
    normalized = strip_section_heading(text)
    if not normalized or CLAUSE_HEADER_RE.match(normalized):
        return False
    if normalized in NONFORMAL_SECTION_HINTS:
        return True
    if len(normalized) <= 22 and not re.search(r"[。；，,]", normalized):
        if text.endswith((":", "：")):
            return True
        if next_text and len(normalize_space(next_text)) >= max(18, len(normalized) + 6):
            return True
    return False


def build_nonformal_section_groups(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    major_heading: str | None = None
    total = len(blocks)
    for index, block in enumerate(blocks):
        text = normalize_space(block.get("text", ""))
        if not text:
            continue
        next_text = normalize_space(blocks[index + 1].get("text", "")) if index + 1 < total else ""
        if is_nonformal_heading(text, next_text):
            heading = strip_section_heading(text)
            level = 2 if text.endswith((":", "：")) else 1
            if level == 1:
                major_heading = heading
                section_path = heading
            else:
                section_path = f"{major_heading} / {heading}" if major_heading and major_heading != heading else heading
            if current and current["blocks"]:
                groups.append(current)
            current = {"label": section_path, "heading": heading, "section_path": section_path, "level": level, "blocks": [block]}
            continue
        if current is None:
            fallback_label = major_heading or strip_section_heading(text)[:80]
            current = {"label": fallback_label, "heading": fallback_label, "section_path": fallback_label, "level": 1, "blocks": [block]}
        else:
            current["blocks"].append(block)
    if current and current["blocks"]:
        groups.append(current)
    return groups


def build_clause_chunks(extracted: dict[str, Any], *, document_type: str = "formal_contract") -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    chunks: list[dict[str, Any]] = []
    parent_chunks: dict[str, dict[str, Any]] = {}
    for group_index, group in enumerate(build_clause_groups(extracted.get("blocks", [])), start=1):
        blocks = group["blocks"]
        label = group.get("label") or normalize_space(blocks[0]["text"])[:80]
        merged_text = "\n".join(block["text"] for block in blocks if normalize_space(block.get("text", "")))
        clause_family = detect_clause_family(merged_text, document_type=document_type)
        parent_chunk_id = f"clause-parent::{group_index:03d}"
        parent_chunks[parent_chunk_id] = chunk_record(
            chunk_id=parent_chunk_id,
            text=merged_text,
            para_start=int(blocks[0].get("para_start", 0)),
            para_end=int(blocks[-1].get("para_end", blocks[-1].get("para_start", 0))),
            page_estimate=int(blocks[0].get("page_estimate", 0)),
            chunk_type="clause_parent",
            clause_label=label,
            source_label=label,
            block_ids=[str(block.get("block_id")) for block in blocks if block.get("block_id")],
            parent_chunk_id=parent_chunk_id,
            clause_family=clause_family,
            document_type=document_type,
            section_label=label,
            section_path=label,
        )
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
                    parent_chunk_id=parent_chunk_id,
                    clause_family=clause_family,
                    document_type=document_type,
                    section_label=label,
                    section_path=label,
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
                    parent_chunk_id=parent_chunk_id,
                    clause_family=clause_family,
                    document_type=document_type,
                    section_label=label,
                    section_path=label,
                )
            )
    return chunks, parent_chunks


def build_nonformal_chunks(extracted: dict[str, Any], *, document_type: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    chunks: list[dict[str, Any]] = []
    parent_chunks: dict[str, dict[str, Any]] = {}
    groups = build_nonformal_section_groups(extracted.get("blocks", []))
    target_size = min(settings.chunk_size, 520)
    overlap = min(settings.chunk_overlap, 80)
    for group_index, group in enumerate(groups, start=1):
        blocks = group["blocks"]
        label = group.get("label") or normalize_space(blocks[0]["text"])[:80]
        section_label = group.get("heading") or label
        section_path = group.get("section_path") or label
        merged_text = "\n".join(block["text"] for block in blocks if normalize_space(block.get("text", "")))
        clause_family = detect_clause_family(merged_text, document_type=document_type)
        parent_chunk_id = f"section-parent::{group_index:03d}"
        parent_chunks[parent_chunk_id] = chunk_record(
            chunk_id=parent_chunk_id,
            text=merged_text,
            para_start=int(blocks[0].get("para_start", 0)),
            para_end=int(blocks[-1].get("para_end", blocks[-1].get("para_start", 0))),
            page_estimate=int(blocks[0].get("page_estimate", 0)),
            chunk_type="section_parent",
            clause_label=section_path,
            source_label=section_path,
            block_ids=[str(block.get("block_id")) for block in blocks if block.get("block_id")],
            parent_chunk_id=parent_chunk_id,
            clause_family=clause_family,
            document_type=document_type,
            section_label=section_label,
            section_path=section_path,
        )
        parts = split_text_with_overlap(merged_text, target_size, overlap)
        for part_index, part in enumerate(parts, start=1):
            suffix = f"__part{part_index:02d}" if len(parts) > 1 else ""
            chunks.append(
                chunk_record(
                    chunk_id=f"section::{group_index:03d}{suffix}",
                    text=part,
                    para_start=int(blocks[0].get("para_start", 0)),
                    para_end=int(blocks[-1].get("para_end", blocks[-1].get("para_start", 0))),
                    page_estimate=int(blocks[0].get("page_estimate", 0)),
                    chunk_type="section",
                    clause_label=section_path,
                    source_label=section_path,
                    block_ids=[str(block.get("block_id")) for block in blocks if block.get("block_id")],
                    parent_chunk_id=parent_chunk_id,
                    clause_family=clause_family,
                    document_type=document_type,
                    section_label=section_label,
                    section_path=section_path,
                )
            )
        member_blocks = blocks[1:] if len(blocks) > 1 else blocks
        for block in member_blocks:
            text = normalize_space(block.get("text", ""))
            if not text or not NONFORMAL_SIGNAL_RE.search(text):
                continue
            chunks.append(
                chunk_record(
                    chunk_id=f"requirement::{group_index:03d}:{int(block.get('para_start', 0)):04d}",
                    text=text,
                    para_start=int(block.get("para_start", 0)),
                    para_end=int(block.get("para_end", block.get("para_start", 0))),
                    page_estimate=int(block.get("page_estimate", 0)),
                    chunk_type="requirement",
                    clause_label=section_path,
                    source_label=section_path,
                    block_ids=[str(block.get("block_id"))] if block.get("block_id") else [],
                    parent_chunk_id=parent_chunk_id,
                    clause_family=clause_family,
                    document_type=document_type,
                    section_label=section_label,
                    section_path=section_path,
                )
            )
    return chunks, parent_chunks, groups


def summarize_action_sentences(text: str) -> str:
    units = [normalize_space(unit) for unit in re.split(r"[。；\n]+", text) if normalize_space(unit)]
    chosen = [unit for unit in units if ACTION_SIGNAL_RE.search(unit)]
    return "；".join(chosen[:3]) if chosen else normalize_space(text)[:300]


def build_structured_chunks(extracted: dict[str, Any], clause_groups: list[dict[str, Any]], *, document_type: str) -> list[dict[str, Any]]:
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
            clause_family=["payment"] if payment_type == "installment" else [],
            document_type=document_type,
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
                clause_family=["milestone", "payment"],
                document_type=document_type,
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
                clause_family=["retention", "payment"],
                document_type=document_type,
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
                document_type=document_type,
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
                clause_family=detect_clause_family(merged_text, document_type=document_type),
                document_type=document_type,
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


def extract_named_markdown_section(text: str, heading: str) -> str:
    lines = strip_frontmatter(text).splitlines()
    capture = False
    captured: list[str] = []
    target = normalize_space(heading).lower()
    for line in lines:
        if line.startswith("## "):
            current = normalize_space(line[3:]).lower()
            if current == target:
                capture = True
                continue
            if capture:
                break
        if capture:
            captured.append(line)
    return "\n".join(captured).strip()


def split_h3_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current_heading and current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = normalize_space(line[4:])
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    if current_heading and current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(heading, body) for heading, body in sections if normalize_space(body)]


def build_contract_summary_chunks(extracted: dict[str, Any], *, document_type: str) -> list[dict[str, Any]]:
    contract_key = extracted.get("contract_key")
    if not contract_key:
        return []
    contract_page = settings.wiki_dir / "contracts" / f"{contract_key}.md"
    if not contract_page.exists():
        return []
    try:
        text = contract_page.read_text(encoding="utf-8")
    except OSError:
        return []
    chunks: list[dict[str, Any]] = []
    for section_name, kind in [("Contract Summary", "wiki_contract_summary"), ("LLM Summary", "wiki_llm_summary")]:
        section_text = extract_named_markdown_section(text, section_name)
        if not section_text:
            continue
        for section_index, (heading, body) in enumerate(split_h3_sections(section_text), start=1):
            families = list(SUMMARY_SECTION_FAMILY_HINTS.get(heading, []))
            detected = detect_clause_family(body, document_type=document_type)
            for family in detected:
                if family not in families:
                    families.append(family)
            chunks.append(
                chunk_record(
                    chunk_id=f"structured::{kind}::{section_index:03d}",
                    text=f"{heading}\n{normalize_space(body)}",
                    para_start=0,
                    para_end=0,
                    page_estimate=0,
                    chunk_type="structured",
                    structured_kind=kind,
                    clause_label=heading,
                    source_label=heading,
                    clause_family=families,
                    document_type=document_type,
                    section_label=heading,
                    section_path=f"{section_name} / {heading}",
                )
            )
    return chunks


def summary_injection_base_score(chunk: dict[str, Any], intents: set[str]) -> float:
    label = normalize_space(str(chunk.get("clause_label") or ""))
    kind = chunk.get("structured_kind")
    if "overview" in intents:
        if label in {"契約目的", "At A Glance"}:
            return 0.36
        if kind == "wiki_contract_summary":
            return 0.30
        return 0.24
    if "payment" in intents:
        if label in {"商務與付款", "Milestone And Payment Structure", "Payment Procedures And Commercial Notes"}:
            return 0.34
        return 0.22
    if "acceptance" in intents:
        if label in {"交付與驗收", "Delivery And Acceptance"}:
            return 0.34
        return 0.22
    if "price_adjustment" in intents or "force_majeure" in intents:
        if label in {"風險與注意事項", "Risks And Open Issues", "商務與付款", "Payment Procedures And Commercial Notes"}:
            return 0.34
        return 0.24
    if "risk" in intents:
        if label in {"風險與注意事項", "Risks And Open Issues"}:
            return 0.34
        return 0.24
    return 0.18


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
    document_type = detect_document_type(extracted)
    if document_type == "formal_contract":
        clause_groups = build_clause_groups(extracted.get("blocks", []))
        body_chunks, _parent_chunks = build_clause_chunks(extracted, document_type=document_type)
    else:
        body_chunks, _parent_chunks, clause_groups = build_nonformal_chunks(extracted, document_type=document_type)
    chunks = body_chunks
    chunks.extend(build_structured_chunks(extracted, clause_groups, document_type=document_type))
    chunks.extend(build_contract_summary_chunks(extracted, document_type=document_type))
    return [chunk for chunk in chunks if chunk.get("text")]


def write_chunk_index(contract_id: str, extracted: dict[str, Any]) -> Path:
    document_type = detect_document_type(extracted)
    if document_type == "formal_contract":
        clause_groups = build_clause_groups(extracted.get("blocks", []))
        body_chunks, parent_chunks = build_clause_chunks(extracted, document_type=document_type)
    else:
        body_chunks, parent_chunks, clause_groups = build_nonformal_chunks(extracted, document_type=document_type)
    chunks = body_chunks + build_structured_chunks(extracted, clause_groups, document_type=document_type)
    chunks.extend(build_contract_summary_chunks(extracted, document_type=document_type))
    tokenized = [tokenize(chunk["text"]) for chunk in chunks]
    tokenization_stats(contract_id, chunks, tokenized)
    index_payload: dict[str, Any] = {
        "contract_id": contract_id,
        "document_type": document_type,
        "chunks": chunks,
        "parent_chunks": parent_chunks,
        "tokenized_chunks": tokenized,
        "embedding_model": settings.embedding_model_name if embedding_model_ready() else None,
    }
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


def search_chunks(contract_id: str, query: str, top_k: int = 5, intents: set[str] | None = None) -> list[dict[str, Any]]:
    return hybrid_search_chunks(contract_id, query, top_k, intents=intents)


def cosine_similarity(query_vector: list[float], chunk_vector: list[float]) -> float:
    return float(sum(left * right for left, right in zip(query_vector, chunk_vector, strict=False)))


def reciprocal_rank_fusion(rankings: list[list[tuple[str, float]]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, (chunk_id, _score) in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + (1.0 / (k + position))
    return fused


def normalize_score_map(pairs: list[tuple[str, float]]) -> dict[str, float]:
    if not pairs:
        return {}
    values = [float(score) for _chunk_id, score in pairs]
    max_value = max(values)
    min_value = min(values)
    if max_value == min_value:
        return {chunk_id: 1.0 for chunk_id, _score in pairs}
    return {chunk_id: (float(score) - min_value) / (max_value - min_value) for chunk_id, score in pairs}


def vector_search(index_payload: dict[str, Any], query: str, top_k: int) -> list[tuple[str, float]]:
    chunks = index_payload.get("chunks", [])
    embeddings = index_payload.get("embeddings")
    if not chunks or not embeddings or not embedding_model_ready():
        return []
    query_vector = embed_query_text(query)
    scored = []
    for chunk, vector in zip(chunks, embeddings, strict=False):
        scored.append((chunk["chunk_id"], cosine_similarity(query_vector, vector)))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]


def qdrant_vector_search(contract_id: str, query: str, top_k: int) -> list[tuple[str, float]]:
    if not embedding_model_ready() or not qdrant_ready():
        return []
    results = search_contract_chunks(contract_id, query, top_k)
    return [(item["chunk_id"], item["retrieval_score"]) for item in results if item.get("chunk_id")]


def hybrid_search_chunks(contract_id: str, query: str, top_k: int = 5, intents: set[str] | None = None) -> list[dict[str, Any]]:
    index_payload = load_chunk_index(contract_id)
    if not index_payload:
        return []
    chunks = index_payload.get("chunks", [])
    parent_chunks = index_payload.get("parent_chunks", {})
    document_type = index_payload.get("document_type") or "formal_contract"
    if not chunks:
        return []

    tokenized_chunks = index_payload.get("tokenized_chunks") or [tokenize(chunk["text"]) for chunk in chunks]
    tokenized_chunks = _retokenize_if_sparse(contract_id, chunks, tokenized_chunks)
    bm25_pairs: list[tuple[str, float]] = []
    if tokenized_chunks:
        bm25_model = BM25Okapi(tokenized_chunks)
        bm25_scores = bm25_model.get_scores(tokenize(query))
        bm25_pairs = sorted(
            [(chunk["chunk_id"], float(score)) for chunk, score in zip(chunks, bm25_scores, strict=False)],
            key=lambda item: item[1],
            reverse=True,
        )[:top_k]

    vector_pairs = qdrant_vector_search(contract_id, query, top_k)
    if not vector_pairs:
        vector_pairs = vector_search(index_payload, query, top_k)

    fused = reciprocal_rank_fusion([bm25_pairs, vector_pairs] if vector_pairs else [bm25_pairs])
    chunk_map = {chunk["chunk_id"]: chunk for chunk in chunks}
    bm25_score_map = dict(bm25_pairs)
    vector_score_map = dict(vector_pairs)
    bm25_norm_map = normalize_score_map(bm25_pairs)
    vector_norm_map = normalize_score_map(vector_pairs)

    base_results: list[dict[str, Any]] = []
    ranked_chunk_ids = sorted(fused.items(), key=lambda item: item[1], reverse=True)[: max(top_k, 12)]
    for rank, (chunk_id, score) in enumerate(ranked_chunk_ids, start=1):
        chunk = chunk_map[chunk_id]
        bm25_weight = 0.28 if document_type in {"spec_rfp", "instruction_manual", "mixed"} else 0.15
        vector_weight = 0.06 if document_type in {"spec_rfp", "instruction_manual", "mixed"} else 0.10
        combined_score = float(score) + (bm25_weight * float(bm25_norm_map.get(chunk_id, 0.0))) + (vector_weight * float(vector_norm_map.get(chunk_id, 0.0)))
        base_results.append(
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
                "parent_chunk_id": chunk.get("parent_chunk_id"),
                "clause_family": chunk.get("clause_family", []),
                "document_type": chunk.get("document_type") or document_type,
                "section_label": chunk.get("section_label"),
                "section_path": chunk.get("section_path"),
                "retrieval_score": combined_score,
                "bm25_score": float(bm25_score_map.get(chunk_id, 0.0)),
                "vector_score": float(vector_score_map.get(chunk_id, 0.0)),
                "retrieval_method": "hybrid_qdrant" if qdrant_ready() and vector_pairs else ("hybrid_local" if vector_pairs else "bm25"),
            }
        )
    intents = intents or set()
    if document_type in {"spec_rfp", "instruction_manual", "mixed"} and ({"overview", "risk", "payment", "acceptance", "price_adjustment", "force_majeure"} & intents):
        summary_candidates = [
            chunk for chunk in chunks
            if chunk.get("chunk_type") == "structured" and chunk.get("structured_kind") in {"wiki_llm_summary", "wiki_contract_summary"}
        ]
        existing_ids = {item["chunk_id"] for item in base_results}
        for chunk in summary_candidates:
            if chunk["chunk_id"] in existing_ids:
                continue
            chunk_id = chunk["chunk_id"]
            base_results.append(
                {
                    "rank": 0,
                    "chunk_id": chunk_id,
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
                    "parent_chunk_id": chunk.get("parent_chunk_id"),
                    "clause_family": chunk.get("clause_family", []),
                    "document_type": chunk.get("document_type") or document_type,
                    "section_label": chunk.get("section_label"),
                    "section_path": chunk.get("section_path"),
                    "retrieval_score": summary_injection_base_score(chunk, intents) + (bm25_weight * float(bm25_norm_map.get(chunk_id, 0.0))) + (vector_weight * float(vector_norm_map.get(chunk_id, 0.0))),
                    "bm25_score": float(bm25_score_map.get(chunk_id, 0.0)),
                    "vector_score": float(vector_score_map.get(chunk_id, 0.0)),
                    "retrieval_method": "summary_injection",
                }
            )
    is_action_like = "action" in intents or "progress_delay" in intents
    is_nonformal = document_type in {"spec_rfp", "instruction_manual", "mixed"}
    parent_expansion_cap = 0 if is_nonformal else (2 if is_action_like else 3)
    parent_expansion_threshold = 1.0 if is_nonformal else (0.04 if is_action_like else 0.02)
    parent_expansion_multiplier = 0.0 if is_nonformal else (0.65 if is_action_like else 0.85)

    direct_parent_ids = {
        item.get("parent_chunk_id")
        for item in base_results
        if item.get("chunk_type") == "clause" and item.get("parent_chunk_id")
    }
    expanded_results: list[dict[str, Any]] = []
    expanded_parent_ids: set[str] = set()
    expanded_clause_families: set[str] = set()
    replaced_child_ids: set[str] = set()
    for item in base_results:
        if len(expanded_results) >= parent_expansion_cap:
            break
        if item.get("chunk_type") != "subclause":
            continue
        if float(item.get("retrieval_score", 0.0)) < parent_expansion_threshold:
            continue
        parent_chunk_id = item.get("parent_chunk_id")
        if not parent_chunk_id or parent_chunk_id in expanded_parent_ids or parent_chunk_id in direct_parent_ids:
            continue
        parent = parent_chunks.get(parent_chunk_id)
        if not parent:
            continue
        parent_families = set(parent.get("clause_family", []))
        if is_action_like and parent_families and parent_families & expanded_clause_families:
            continue
        expanded_parent_ids.add(parent_chunk_id)
        expanded_clause_families.update(parent_families)
        replaced_child_ids.add(item["chunk_id"])
        expanded_results.append(
            {
                "rank": 0,
                "chunk_id": parent["chunk_id"],
                "text_snippet": parent["text"][:500],
                "para_start": parent["para_start"],
                "para_end": parent["para_end"],
                "page_estimate": parent["page_estimate"],
                "chunk_type": "clause",
                "clause_label": parent.get("clause_label"),
                "structured_kind": parent.get("structured_kind"),
                "wiki_source_path": parent.get("wiki_source_path"),
                "source_label": parent.get("source_label"),
                "block_ids": parent.get("block_ids", []),
                "parent_chunk_id": parent["chunk_id"],
                "clause_family": parent.get("clause_family", []),
                "document_type": parent.get("document_type") or document_type,
                "section_label": parent.get("section_label"),
                "section_path": parent.get("section_path"),
                "retrieval_score": float(item["retrieval_score"]) * parent_expansion_multiplier,
                "bm25_score": float(item.get("bm25_score", 0.0)),
                "vector_score": float(item.get("vector_score", 0.0)),
                "retrieval_method": "parent_expansion",
                "triggered_by": item["chunk_id"],
            }
        )

    deduped_results: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for item in sorted(base_results + expanded_results, key=lambda row: float(row["retrieval_score"]), reverse=True):
        if item["chunk_id"] in replaced_child_ids and item.get("chunk_type") == "subclause":
            continue
        if item["chunk_id"] in seen_chunk_ids:
            continue
        seen_chunk_ids.add(item["chunk_id"])
        deduped_results.append(item)
        if len(deduped_results) >= top_k:
            break
    for rank, item in enumerate(deduped_results, start=1):
        item["rank"] = rank
    return deduped_results
