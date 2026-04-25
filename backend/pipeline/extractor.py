from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from backend.config import settings

TOTAL_PATTERNS = [
    re.compile(r"新臺幣\s*([\d,]+)\s*元"),
    re.compile(r"NT\$\s*([\d,]+)"),
    re.compile(r"(?:總價|契約總價|承攬總價|工程總價|合約總價)[：為係計]?\s*[新臺幣NT\$\s]*([\d,]+)\s*元"),
]
MILESTONE_PATTERN = re.compile(r"(第[一二三四五六七八九十\d]+期[：:、]?\s*[^\n，。]*)")
PAYMENT_ITEM_PATTERN = re.compile(r"^((?:簽約金|工程設備款|設備安裝工程款|功能檢測款|功能整合款|尾款)[^：:\n]*|第[一二三四五六七八九十\d]+期[：:、]?\s*[^\n，。]*)")
AMOUNT_PATTERN = re.compile(r"(?:給付|付款|支付|即)\s*([\d,]+)\s*元")
PERCENT_PATTERN = re.compile(r"([\d.]+)\s*[％%]")
PAYMENT_PATTERN = re.compile(r"(驗收合格後?|簽訂後|完成.*?後|取得.*?後|核定後|確認後)[，,]?\s*(?:甲方|客戶)?(?:應)?(?:給付|付款|支付)")
WORK_ITEM_PATTERN = re.compile(r"^[\-•\d一二三四五六七八九十]+[.、\s]")
CHINESE_NUMERAL_PATTERN = re.compile(r"[零一二三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟兩]+")
INSTALLMENT_PATTERN = re.compile(r"分([一二三四五六七八九十\d]+)期")

ZH_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "貳": 2,
    "參": 3,
    "肆": 4,
    "伍": 5,
    "陸": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
    "兩": 2,
}
ZH_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000, "萬": 10000, "億": 100000000}


def zh_to_int(raw_value: str) -> int | None:
    total = 0
    section = 0
    number = 0
    for char in raw_value:
        if char in ZH_DIGITS:
            number = ZH_DIGITS[char]
        elif char in ZH_UNITS:
            unit = ZH_UNITS[char]
            if unit >= 10000:
                section = (section + (number or 0)) * unit
                total += section
                section = 0
                number = 0
            else:
                section += (number or 1) * unit
                number = 0
    return total + section + number if (total + section + number) > 0 else None


def clean_number(raw_value: str | None) -> int | None:
    if not raw_value:
        return None
    digits = raw_value.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def build_citation(source_file: str, paragraph: dict[str, Any], snippet: str, field_name: str, regex_pattern: str | None) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "source_file": source_file,
        "para_start": paragraph["paragraph_index"],
        "para_end": paragraph["paragraph_index"],
        "page_estimate": paragraph["page_estimate"],
        "char_offset_start": max(paragraph["text"].find(snippet), 0),
        "char_offset_end": max(paragraph["text"].find(snippet), 0) + len(snippet),
        "text_snippet": snippet[:300],
        "block_id": paragraph["block_id"],
        "extraction_method": "regex",
        "regex_pattern": regex_pattern,
    }


def extract_contract_name(source_file: str, paragraphs: list[dict[str, Any]]) -> str:
    for index, paragraph in enumerate(paragraphs[:20]):
        text = paragraph["text"].strip()
        if text in {"專案名稱", "工程案名稱", "工程名稱"} and index + 1 < len(paragraphs):
            value = paragraphs[index + 1]["text"].strip().strip("：:")
            if value:
                return value
        if "工程名稱" in text and "：" in text:
            return text.split("：", 1)[1].strip()
        if "工程案之工程名稱" in text and "：" in text:
            return text.split("：", 1)[1].strip()
    if paragraphs:
        head = paragraphs[0]["text"].strip()
        if len(head) <= 80 and head not in {"專案名稱", "工程案名稱", "工程名稱"}:
            return head
    return source_file.rsplit(".", 1)[0]


def extract_total_amount(source_file: str, paragraphs: list[dict[str, Any]]) -> tuple[int | None, list[dict[str, Any]], list[int]]:
    citations: list[dict[str, Any]] = []
    numeric_candidates: list[int] = []
    total_context_markers = ("總價", "契約總價", "承攬總價", "工程總價", "合約總價")
    for paragraph in paragraphs:
        text = paragraph["text"]
        for pattern in TOTAL_PATTERNS:
            match = pattern.search(text)
            if match:
                amount = clean_number(match.group(1))
                if amount is not None:
                    citations.append(build_citation(source_file, paragraph, match.group(0), "total_amount", pattern.pattern))
                    numeric_candidates.append(amount)
        zh_match = CHINESE_NUMERAL_PATTERN.search(text)
        if zh_match and any(marker in text for marker in total_context_markers):
            amount = zh_to_int(zh_match.group(0))
            if amount:
                numeric_candidates.append(amount)
                citations.append(build_citation(source_file, paragraph, zh_match.group(0), "total_amount", CHINESE_NUMERAL_PATTERN.pattern))
    if not numeric_candidates:
        return None, citations, []
    best_value = max(numeric_candidates)
    return best_value, citations, numeric_candidates


def extract_work_items(paragraphs: list[dict[str, Any]], start_index: int) -> list[str]:
    work_items: list[str] = []
    for paragraph in paragraphs[start_index + 1 : start_index + 6]:
        text = paragraph["text"].strip()
        if MILESTONE_PATTERN.search(text) or PAYMENT_ITEM_PATTERN.search(text):
            break
        if WORK_ITEM_PATTERN.search(text):
            work_items.append(text)
    return work_items


def extract_installment_count(paragraphs: list[dict[str, Any]]) -> int | None:
    for paragraph in paragraphs:
        match = INSTALLMENT_PATTERN.search(paragraph["text"])
        if not match:
            continue
        token = match.group(1)
        if token.isdigit():
            return int(token)
        converted = zh_to_int(token)
        if converted:
            return converted
    return None


def is_payment_header(text: str) -> re.Match[str] | None:
    return MILESTONE_PATTERN.search(text) or PAYMENT_ITEM_PATTERN.search(text)


def extract_milestones(source_file: str, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    milestones: list[dict[str, Any]] = []
    for offset, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        milestone_match = is_payment_header(text)
        if not milestone_match:
            continue
        title = milestone_match.group(1).strip()
        milestone_citations = [build_citation(source_file, paragraph, milestone_match.group(0), "milestone.name", MILESTONE_PATTERN.pattern)]
        amount = None
        percentage = None
        payment_condition = None
        acceptance_criteria = None
        related_paragraphs = paragraphs[offset : offset + 5]
        joined_text = " ".join(item["text"] for item in related_paragraphs)
        for related in related_paragraphs:
            related_text = related["text"]
            amount_match = AMOUNT_PATTERN.search(related_text)
            if amount_match and amount is None:
                amount = clean_number(amount_match.group(1))
                milestone_citations.append(build_citation(source_file, related, amount_match.group(0), "milestone.amount", AMOUNT_PATTERN.pattern))
            percent_match = PERCENT_PATTERN.search(related_text)
            if percent_match and percentage is None:
                percentage = float(percent_match.group(1))
                milestone_citations.append(build_citation(source_file, related, percent_match.group(0), "milestone.percentage", PERCENT_PATTERN.pattern))
            payment_match = PAYMENT_PATTERN.search(related_text)
            if payment_match and payment_condition is None:
                payment_condition = payment_match.group(0)
                milestone_citations.append(build_citation(source_file, related, payment_condition, "milestone.payment_condition", PAYMENT_PATTERN.pattern))
            if "驗收" in related_text and acceptance_criteria is None:
                acceptance_criteria = related_text[:300]
                milestone_citations.append(build_citation(source_file, related, acceptance_criteria, "milestone.acceptance_criteria", None))
        if amount is None:
            joined_amount_match = AMOUNT_PATTERN.search(joined_text)
            if joined_amount_match:
                amount = clean_number(joined_amount_match.group(1))
                for related in related_paragraphs:
                    related_amount_match = AMOUNT_PATTERN.search(related["text"])
                    if related_amount_match:
                        milestone_citations.append(build_citation(source_file, related, related_amount_match.group(0), "milestone.amount", AMOUNT_PATTERN.pattern))
                        break
        if percentage is None:
            joined_percent_match = PERCENT_PATTERN.search(joined_text)
            if joined_percent_match:
                percentage = float(joined_percent_match.group(1))
                for related in related_paragraphs:
                    related_percent_match = PERCENT_PATTERN.search(related["text"])
                    if related_percent_match:
                        milestone_citations.append(build_citation(source_file, related, related_percent_match.group(0), "milestone.percentage", PERCENT_PATTERN.pattern))
                        break
        work_items = extract_work_items(paragraphs, offset)
        if work_items:
            work_item_text = "\n".join(work_items)[:300]
            milestone_citations.append(build_citation(source_file, paragraph, work_item_text, "milestone.work_items", None))
        milestones.append(
            {
                "milestone_id": f"m_{uuid4().hex[:10]}",
                "name": title,
                "amount": amount,
                "percentage": percentage,
                "work_items": work_items,
                "acceptance_criteria": acceptance_criteria,
                "payment_condition": payment_condition,
                "status": "pending_acceptance",
                "citations": milestone_citations,
                "source_order": len(milestones) + 1,
            }
        )
    return milestones


def detect_tax_included(paragraphs: list[dict[str, Any]]) -> bool:
    return any("含稅" in item["text"] for item in paragraphs)


def build_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "block_id": item["block_id"],
            "text": item["text"],
            "para_start": item["paragraph_index"],
            "para_end": item["paragraph_index"],
            "page_estimate": item["page_estimate"],
        }
        for item in paragraphs
    ]


def extract_contract_data(document: dict[str, Any]) -> dict[str, Any]:
    source_file = document["source_file"]
    paragraphs = document["paragraphs"]
    total_amount, total_citations, total_candidates = extract_total_amount(source_file, paragraphs)
    milestones = extract_milestones(source_file, paragraphs)
    declared_installment_count = extract_installment_count(paragraphs)
    extraction_method = "regex"
    validation: list[dict[str, Any]] = []
    confidence = 0
    if total_amount is not None:
        confidence += 40
    if milestones:
        confidence += 20
    if all(m["amount"] is not None for m in milestones) and milestones:
        confidence += 20
    if any(m["percentage"] is not None for m in milestones):
        confidence += 10
    if any(m["payment_condition"] for m in milestones):
        confidence += 10

    if total_amount is None:
        validation.append({"code": "missing_total_amount", "severity": "ERROR", "message": "No contract total amount was extracted.", "citations": []})
    if not milestones:
        validation.append({"code": "missing_milestones", "severity": "WARNING", "message": "No milestone blocks were extracted.", "citations": []})
    if not total_citations and total_amount is not None:
        validation.append({"code": "missing_total_citation", "severity": "ERROR", "message": "Total amount lacks a traceable citation.", "citations": []})
    if total_amount is None and not milestones:
        document["doc_category"] = "rfp"

    all_citations = total_citations + [citation for milestone in milestones for citation in milestone["citations"]]
    return {
        "contract_name": extract_contract_name(source_file, paragraphs),
        "total_amount": total_amount,
        "currency": settings.default_currency,
        "contract_type": "lump_sum",
        "total_amount_is_tax_included": detect_tax_included(paragraphs),
        "doc_category": document["doc_category"],
        "milestones": milestones,
        "citations": all_citations,
        "validation": validation,
        "extraction_method": extraction_method,
        "confidence": confidence,
        "source_candidates": {"total_amount_candidates": total_candidates},
        "declared_installment_count": declared_installment_count,
        "blocks": build_blocks(paragraphs),
        "raw_text_preview": "\n".join(item["text"] for item in paragraphs[:20]),
    }


def serialize_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
