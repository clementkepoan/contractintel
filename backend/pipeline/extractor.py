from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from backend.config import settings

TOTAL_PATTERNS = [
    re.compile(r"新[臺台]幣\s*(?:[零一二三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟兩]+)?\s*[（(]?(?:NT\$|NTD|TWD)?\s*([\d,]+)\s*[）)]?\s*元?"),
    re.compile(r"NT\$\s*([\d,]+)"),
    re.compile(r"(?:總價|契約總價|承攬總價|工程總價|合約總價)[：為係計修訂]*\s*[新臺台幣NTD\$\s（(]*([\d,]+)\s*[）)]?\s*元?"),
]
MILESTONE_PATTERN = re.compile(
    r"((?:【?里程碑[一二三四五六七八九十A-Z\d]+】?|工程節點[一二三四五六七八九十\d]+|第[一二三四五六七八九十\d]+期款?|階段[一二三四五六七八九十\d]+尾?款?|Phase\s*\d+|節點\d+)[：:、）)]?\s*[^\n，。]*)",
    re.IGNORECASE,
)
PAYMENT_ITEM_PATTERN = re.compile(
    r"^((?:\[V\d修訂\]\s*)?(?:簽約金|工程設備款|設備安裝工程款|功能檢測款|功能整合款|尾款)[^：:\n]*|(?:\[V\d修訂\]\s*)?第[一二三四五六七八九十\d]+期款?[：:、）)]?\s*[^\n，。]*)"
)
AMOUNT_PATTERN = re.compile(r"(?:給付|付款|支付|付款金額|即)[：:\s]*(?:新[臺台]幣\s*)?(?:NT\$|NTD|TWD)?\s*([\d,]+)\s*元?", re.IGNORECASE)
ANY_AMOUNT_PATTERN = re.compile(r"(?:NT\$|NTD|TWD|新[臺台]幣)\s*([\d,]+)|([\d,]+)\s*元", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"([\d.]+)\s*[％%]")
PAYMENT_PATTERN = re.compile(r"(驗收合格後?|簽訂後|完成.*?後|取得.*?後|核定後|確認後)[，,]?\s*(?:甲方|客戶)?(?:應)?(?:給付|付款|支付)")
WORK_ITEM_PATTERN = re.compile(r"^(?:[\-•●‧]\s*|\d+[.、\s]+|[一二三四五六七八九十]+[.、\s]+)")
CHINESE_NUMERAL_PATTERN = re.compile(r"[零一二三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟兩]+")
INSTALLMENT_PATTERN = re.compile(r"分([一二三四五六七八九十\d]+)期")
SECTION_HEADING_PATTERN = re.compile(r"^第[一二三四五六七八九十\d]+條")
CHECKPOINT_PATTERN = re.compile(r"(查驗點[一二三四五六七八九十\d]+[^\n，。]*)")

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


def is_deprecated_text(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(("[舊版", "[廢除", "[已廢除]")) or "已廢除" in stripped[:40]


def live_paragraphs(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [paragraph for paragraph in paragraphs if not is_deprecated_text(paragraph["text"])]


def deprecated_paragraphs(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [paragraph for paragraph in paragraphs if is_deprecated_text(paragraph["text"])]


def ordinal_from_text(text: str) -> int | None:
    match = re.search(r"工程節點([一二三四五六七八九十\d]+)|第([一二三四五六七八九十\d]+)期|里程碑([A-Z一二三四五六七八九十\d]+)|階段([一二三四五六七八九十\d]+)|Phase\s*(\d+)|節點(\d+)|查驗點([一二三四五六七八九十\d]+)", text, re.IGNORECASE)
    if not match:
        return None
    token = next((value for value in match.groups() if value), None)
    if token is None:
        return None
    token = token.upper()
    if token.isdigit():
        return int(token)
    if len(token) == 1 and "A" <= token <= "Z":
        return ord(token) - ord("A") + 1
    return zh_to_int(token)


def milestone_term_type(text: str) -> str | None:
    if "工程節點" in text:
        return "工程節點"
    if "里程碑" in text:
        return "里程碑"
    if re.search(r"第[一二三四五六七八九十\d]+期", text):
        return "分期"
    if "階段" in text:
        return "階段"
    if re.search(r"Phase|節點\d+", text, re.IGNORECASE):
        return "phase"
    return None


def clean_work_item(text: str) -> str:
    return re.sub(r"^(?:[\-•●‧\s]*|\d+[.、\s]+|[一二三四五六七八九十]+[.、\s]+)", "", text.strip()).strip()


def extract_amount_from_text(text: str) -> int | None:
    match = AMOUNT_PATTERN.search(text)
    if match:
        return clean_number(match.group(1))
    if any(marker in text for marker in ("給付", "付款", "金額", "保固保證金", "合約總價")):
        any_match = ANY_AMOUNT_PATTERN.search(text)
        if any_match:
            return clean_number(any_match.group(1) or any_match.group(2))
    return None


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


def extract_multi_currency_total(source_file: str, paragraphs: list[dict[str, Any]]) -> tuple[int | None, str | None, list[dict[str, Any]], list[int], list[dict[str, Any]]]:
    joined = "\n".join(paragraph["text"] for paragraph in paragraphs)
    has_local = bool(re.search(r"NTD|TWD|NT\$|新[臺台]幣", joined, re.IGNORECASE))
    has_foreign = bool(re.search(r"USD|US\$|美元|EUR|歐元", joined, re.IGNORECASE))
    if not (has_local and has_foreign):
        return None, None, [], [], []

    citations: list[dict[str, Any]] = []
    candidates: list[int] = []
    ntd_rows: list[tuple[int, dict[str, Any], bool]] = []
    usd_rows: list[tuple[int, dict[str, Any]]] = []
    for paragraph in paragraphs:
        text = paragraph["text"]
        if re.search(r"NTD|TWD|NT\$|新[臺台]幣", text, re.IGNORECASE):
            for raw in re.findall(r"(?:NTD|TWD|NT\$|新[臺台]幣(?:（NTD）)?)\s*([\d,]+)|([\d,]+)\s*\|\s*新[臺台]幣", text, re.IGNORECASE):
                amount = clean_number(raw[0] or raw[1])
                if amount:
                    is_total = any(marker in text for marker in ("合約總額", "換算", "總價", "總額", "合計"))
                    ntd_rows.append((amount, paragraph, is_total))
                    candidates.append(amount)
        if re.search(r"USD|US\$|美元", text, re.IGNORECASE):
            for raw in re.findall(r"(?:USD|US\$|美元(?:（USD）)?)\s*([\d,]+)|([\d,]+)\s*\|\s*美元", text, re.IGNORECASE):
                amount = clean_number(raw[0] or raw[1])
                if amount:
                    usd_rows.append((amount, paragraph))

    total_row = max((row for row in ntd_rows if row[2]), default=None, key=lambda item: item[0])
    domestic_row = max((row for row in ntd_rows if not row[2]), default=None, key=lambda item: item[0])
    usd_row = max(usd_rows, default=None, key=lambda item: item[0])
    rate_match = re.search(r"匯率\s*([\d.]+)|rate\s*([\d.]+)|匯率為?\s*([\d.]+)", joined, re.IGNORECASE)
    rate = float(next((part for part in rate_match.groups() if part), "0")) if rate_match else None
    if not rate:
        row_rate = re.search(r"匯率\s*([\d.]+)", total_row[1]["text"] if total_row else "")
        rate = float(row_rate.group(1)) if row_rate else None

    total_amount = total_row[0] if total_row else None
    if total_amount is None and domestic_row and usd_row and rate:
        total_amount = domestic_row[0] + round(usd_row[0] * rate)
    if total_amount is None:
        return None, "MULTI", citations, candidates, []

    if total_row:
        citations.append(build_citation(source_file, total_row[1], str(total_row[0]), "total_amount", "multi_currency_table"))
    breakdown: list[dict[str, Any]] = []
    if domestic_row:
        breakdown.append({"amount": domestic_row[0], "currency": "NTD"})
    if usd_row:
        usd_breakdown: dict[str, Any] = {"amount": usd_row[0], "currency": "USD"}
        if rate:
            usd_breakdown["rate"] = rate
            usd_breakdown["ntd_equivalent"] = round(usd_row[0] * rate)
        breakdown.append(usd_breakdown)
    return total_amount, "MULTI", citations, candidates, breakdown


def extract_total_amount(source_file: str, paragraphs: list[dict[str, Any]]) -> tuple[int | None, list[dict[str, Any]], list[int]]:
    citations: list[dict[str, Any]] = []
    numeric_candidates: list[int] = []
    total_context_markers = ("總價", "契約總價", "承攬總價", "工程總價", "合約總價")
    for paragraph in paragraphs:
        text = paragraph["text"]
        if not any(marker in text for marker in total_context_markers):
            continue
        if "%" in text and not re.search(r"NT\$|NTD|TWD|新[臺台]幣|元", text, re.IGNORECASE):
            continue
        for pattern in TOTAL_PATTERNS:
            match = pattern.search(text)
            if match:
                amount = clean_number(match.group(1))
                if amount is not None:
                    citations.append(build_citation(source_file, paragraph, match.group(0), "total_amount", pattern.pattern))
                    numeric_candidates.append(amount)
        zh_match = CHINESE_NUMERAL_PATTERN.search(text)
        if zh_match and any(marker in text for marker in total_context_markers) and any(marker in zh_match.group(0) for marker in ("十", "百", "千", "萬", "億", "拾", "佰", "仟")):
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
    start_text = paragraphs[start_index]["text"]
    collecting = milestone_term_type(start_text) in {"工程節點", "phase"}
    for paragraph in paragraphs[start_index + 1 :]:
        text = paragraph["text"].strip()
        if not text:
            if collecting:
                break
            continue
        if is_payment_header(text) or SECTION_HEADING_PATTERN.search(text):
            break
        if text.rstrip("：:") in {"工作項目", "完成條件"}:
            collecting = True
            continue
        if collecting and (text.startswith("【") or text.startswith("附件") or "付款比例" in text or "付款金額" in text or "付款時機" in text or "合計" in text):
            break
        if WORK_ITEM_PATTERN.search(text) or collecting:
            if any(marker in text for marker in ("付款時機", "付款金額", "驗收條件")) and not WORK_ITEM_PATTERN.search(text):
                break
            cleaned = clean_work_item(text)
            if cleaned:
                work_items.append(cleaned)
    return work_items


def extract_keyword_blocks(paragraphs: list[dict[str, Any]], keywords: tuple[str, ...], limit: int = 8) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        text = paragraph["text"].strip()
        if not text or text in seen:
            continue
        if any(keyword in text for keyword in keywords):
            results.append(text[:300])
            seen.add(text)
        if len(results) >= limit:
            break
    return results


def extract_document_notes(paragraphs: list[dict[str, Any]], doc_category: str) -> dict[str, list[str]]:
    scope_keywords = ("施工內容", "工程說明", "系統", "平台", "整合", "監控", "APP", "智慧", "能源管理")
    acceptance_keywords = ("驗收", "查驗", "測試", "審核", "完工", "連動測試")
    safety_keywords = ("安全", "職業安全衛生", "勞工保險", "教育訓練", "督導", "防護")
    warranty_keywords = ("保固", "更換", "替換")

    notes = {
        "scope_items": extract_keyword_blocks(paragraphs, scope_keywords),
        "acceptance_requirements": extract_keyword_blocks(paragraphs, acceptance_keywords),
        "safety_requirements": extract_keyword_blocks(paragraphs, safety_keywords),
        "warranty_requirements": extract_keyword_blocks(paragraphs, warranty_keywords),
    }
    if doc_category == "contract":
        notes["scope_items"] = notes["scope_items"][:4]
    return notes


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
    if SECTION_HEADING_PATTERN.search(text):
        return None
    return MILESTONE_PATTERN.search(text) or PAYMENT_ITEM_PATTERN.search(text)


def extract_milestones(source_file: str, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    milestones_by_key: dict[int | str, dict[str, Any]] = {}
    ordered_keys: list[int | str] = []
    for offset, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        milestone_match = is_payment_header(text)
        if not milestone_match:
            continue
        title = milestone_match.group(1).strip()
        ordinal = ordinal_from_text(title)
        key: int | str = ordinal if ordinal is not None else f"offset_{offset}"
        milestone_citations = [build_citation(source_file, paragraph, milestone_match.group(0), "milestone.name", MILESTONE_PATTERN.pattern)]
        amount = None
        percentage = None
        payment_condition = None
        acceptance_criteria = None
        related_paragraphs: list[dict[str, Any]] = []
        for related in paragraphs[offset : offset + 8]:
            if related is not paragraph and is_payment_header(related["text"]):
                break
            if related is not paragraph and SECTION_HEADING_PATTERN.search(related["text"]):
                break
            related_paragraphs.append(related)
        joined_text = " ".join(item["text"] for item in related_paragraphs)
        for related in related_paragraphs:
            related_text = related["text"]
            parsed_amount = extract_amount_from_text(related_text)
            if parsed_amount is not None and amount is None:
                amount = parsed_amount
                milestone_citations.append(build_citation(source_file, related, str(parsed_amount), "milestone.amount", AMOUNT_PATTERN.pattern))
            percent_match = PERCENT_PATTERN.search(related_text)
            if percent_match and percentage is None:
                if related is paragraph or any(marker in related_text for marker in ("付款比例", "占合約總價", "合約總價之")):
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
        if key not in milestones_by_key:
            milestones_by_key[key] = {
                "milestone_id": f"m_{uuid4().hex[:10]}",
                "name": title,
                "amount": amount,
                "percentage": percentage,
                "work_items": work_items,
                "acceptance_criteria": acceptance_criteria,
                "payment_condition": payment_condition,
                "status": "pending_acceptance",
                "citations": milestone_citations,
                "source_order": len(ordered_keys) + 1,
            }
            ordered_keys.append(key)
            continue
        existing = milestones_by_key[key]
        existing["citations"].extend(milestone_citations)
        existing["work_items"] = existing.get("work_items") or work_items
        if amount is not None:
            existing["amount"] = amount
            existing["name"] = title
        if percentage is not None:
            existing["percentage"] = percentage
        if payment_condition and not existing.get("payment_condition"):
            existing["payment_condition"] = payment_condition
        if acceptance_criteria and not existing.get("acceptance_criteria"):
            existing["acceptance_criteria"] = acceptance_criteria
    return [milestones_by_key[key] for key in ordered_keys]


def extract_progress_checkpoints(source_file: str, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checkpoints: list[dict[str, Any]] = []
    for offset, paragraph in enumerate(paragraphs):
        match = CHECKPOINT_PATTERN.search(paragraph["text"])
        if not match:
            continue
        work_items = extract_work_items(paragraphs, offset)
        checkpoints.append(
            {
                "name": match.group(1),
                "work_items": work_items,
                "citations": [build_citation(source_file, paragraph, match.group(0), "progress_checkpoint.name", CHECKPOINT_PATTERN.pattern)],
                "source_order": len(checkpoints) + 1,
            }
        )
    return checkpoints


def detect_payment_type(paragraphs: list[dict[str, Any]]) -> str:
    joined = "\n".join(paragraph["text"] for paragraph in paragraphs)
    if "非分期付款" in joined or "一次付款" in joined or "一次性付款" in joined:
        if "保固保證金" in joined or "扣留" in joined:
            return "single_with_retention"
        return "single_payment"
    return "installment"


def build_single_payment_milestones(source_file: str, paragraphs: list[dict[str, Any]], total_amount: int | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if total_amount is None:
        return [], None
    final_payment: dict[str, Any] | None = None
    retention: dict[str, Any] | None = None
    for paragraph in paragraphs:
        text = paragraph["text"]
        if final_payment is None and ("合約總價 95%" in text or "給付合約總價" in text):
            amount = extract_amount_from_text(text) or round(total_amount * 0.95)
            final_payment = {
                "milestone_id": f"m_{uuid4().hex[:10]}",
                "name": "最終驗收付款",
                "type": "single_payment",
                "amount": amount,
                "percentage": 95.0,
                "work_items": [],
                "acceptance_criteria": text[:300],
                "payment_condition": "驗收合格後請款付款",
                "status": "pending_acceptance",
                "citations": [build_citation(source_file, paragraph, text[:120], "milestone.payment_condition", None)],
                "source_order": 1,
            }
        if retention is None and "保固保證金" in text:
            amount = extract_amount_from_text(text) or round(total_amount * 0.05)
            retention = {
                "type": "retention",
                "amount": amount,
                "percentage": 5.0,
                "release_condition": "保固期屆滿且無未解決瑕疵",
                "release_after_months": 24 if "2年" in text or "24" in text else None,
                "citations": [build_citation(source_file, paragraph, text[:120], "retention", None)],
            }
    milestones = [final_payment] if final_payment else []
    if retention:
        milestones.append(
            {
                "milestone_id": f"m_{uuid4().hex[:10]}",
                "name": "保固保證金退還",
                "type": "retention",
                "amount": retention["amount"],
                "percentage": retention["percentage"],
                "work_items": [],
                "acceptance_criteria": retention["release_condition"],
                "payment_condition": retention["release_condition"],
                "status": "retention_pending",
                "citations": retention["citations"],
                "source_order": 2,
            }
        )
    return milestones, retention


def extract_document_versions(source_file: str, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        text = paragraph["text"]
        match = re.search(r"(V\d+(?:\.\d+)?)\s*\|\s*(\d{4}/\d{1,2}/\d{1,2})\s*\|\s*([^|]+)", text)
        if match:
            versions.append(
                {
                    "version": match.group(1),
                    "date": match.group(2),
                    "summary": match.group(3).strip(),
                    "citations": [build_citation(source_file, paragraph, match.group(0), "document_versions", "version_table")],
                }
            )
    return versions


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
    active_paragraphs = live_paragraphs(paragraphs)
    retired_paragraphs = deprecated_paragraphs(paragraphs)
    doc_notes = extract_document_notes(active_paragraphs, document["doc_category"])
    multi_total, multi_currency, multi_citations, multi_candidates, currency_breakdown = extract_multi_currency_total(source_file, active_paragraphs)
    if multi_total is not None:
        total_amount, total_citations, total_candidates = multi_total, multi_citations, multi_candidates
        currency = multi_currency or "MULTI"
    else:
        total_amount, total_citations, total_candidates = extract_total_amount(source_file, active_paragraphs)
        currency = settings.default_currency
    payment_type = detect_payment_type(active_paragraphs)
    if payment_type.startswith("single"):
        milestones, retention = build_single_payment_milestones(source_file, active_paragraphs, total_amount)
    else:
        milestones = extract_milestones(source_file, active_paragraphs)
        retention = None
    superseded_milestones = extract_milestones(source_file, retired_paragraphs) if retired_paragraphs else []
    progress_checkpoints = extract_progress_checkpoints(source_file, active_paragraphs)
    declared_installment_count = extract_installment_count(active_paragraphs)
    document_versions = extract_document_versions(source_file, paragraphs)
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
        validation.append({"code": "missing_total_amount", "severity": "WARNING", "message": "No total contract amount found; document may be an RFP or pre-award document.", "citations": []})
    if not milestones:
        validation.append({"code": "missing_milestones", "severity": "WARNING", "message": "No milestone blocks were extracted.", "citations": []})
    if not total_citations and total_amount is not None:
        validation.append({"code": "missing_total_citation", "severity": "ERROR", "message": "Total amount lacks a traceable citation.", "citations": []})
    if total_amount is None and not milestones and document["doc_category"] == "contract":
        document["doc_category"] = "rfp"
    milestone_terms = {term for paragraph in active_paragraphs if is_payment_header(paragraph["text"]) and (term := milestone_term_type(paragraph["text"]))}
    if len(milestone_terms) > 1:
        validation.append(
            {
                "code": "milestone_terminology_inconsistency",
                "severity": "INFO",
                "message": f"Milestone terminology inconsistency detected: document uses {len(milestone_terms)} naming conventions; normalized by ordinal position.",
                "citations": [],
            }
        )
    if currency == "MULTI" and not any("rate" in item for item in currency_breakdown):
        validation.append({"code": "multi_currency_missing_rate", "severity": "WARNING", "message": "Multi-currency contract: exchange rate assumption required.", "citations": []})
    if progress_checkpoints and payment_type.startswith("single"):
        validation.append(
            {
                "code": "progress_checkpoints_not_payment_milestones",
                "severity": "INFO",
                "message": f"{len(progress_checkpoints)} progress checkpoints found; these do not trigger payment.",
                "citations": [cite for checkpoint in progress_checkpoints for cite in checkpoint["citations"]][:4],
            }
        )
    if retired_paragraphs:
        validation.append(
            {
                "code": "version_conflict_detected",
                "severity": "WARNING",
                "message": "Version conflict detected: deprecated clauses were excluded from primary extraction and stored as superseded content.",
                "citations": [build_citation(source_file, paragraph, paragraph["text"][:120], "deprecated_clause", None) for paragraph in retired_paragraphs[:4]],
            }
        )

    all_citations = total_citations + [citation for milestone in milestones for citation in milestone["citations"]]
    return {
        "contract_name": extract_contract_name(source_file, paragraphs),
        "total_amount": total_amount,
        "currency": currency,
        "contract_type": "lump_sum",
        "payment_type": payment_type,
        "total_amount_is_tax_included": detect_tax_included(paragraphs),
        "doc_category": document["doc_category"],
        "milestones": milestones,
        "superseded_milestones": superseded_milestones,
        "has_version_conflict": bool(retired_paragraphs),
        "document_versions": document_versions,
        "currency_breakdown": currency_breakdown,
        "retention": retention,
        "progress_checkpoints": progress_checkpoints,
        "citations": all_citations,
        "validation": validation,
        "extraction_method": extraction_method,
        "confidence": confidence,
        "source_candidates": {"total_amount_candidates": total_candidates},
        "declared_installment_count": declared_installment_count,
        "blocks": build_blocks(paragraphs),
        "raw_text_preview": "\n".join(item["text"] for item in paragraphs[:20]),
        **doc_notes,
    }


def serialize_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
