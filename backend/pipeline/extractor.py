from __future__ import annotations

import copy
import json
import re
from typing import Any
from uuid import uuid4

from backend.config import settings
from backend.pipeline.extractor_llm import extract_contract_with_llm
from backend.pipeline.validation import validate_contract_data

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
WORK_ITEM_LABELS = {"工作項目", "完成條件"}
ADMINISTRATIVE_WORK_ITEM_MARKERS = (
    "乙方應依前項約定",
    "開具請領發票",
    "請領發票憑證",
    "相關請款文件",
    "發票日後",
    "給付該期款項",
    "取得全部或當期工程款",
    "暫行停止計價付款",
    "暫停付款",
    "甲方有權暫行停止計價付款",
    "甲方有權暫停付款",
    "付款條件",
    "付款辦法",
    "請款及付款日期",
)
WORK_ITEM_STOP_MARKERS = (
    "付款時機",
    "付款金額",
    "驗收條件",
    "甲方應給付",
    "本契約總價",
    "工程總價",
    "契約總價",
)
TASKISH_MARKERS = (
    "完成",
    "提交",
    "送審",
    "投保",
    "進場",
    "安裝",
    "測試",
    "整合",
    "交貨",
    "提出",
    "訓練",
    "圖說",
    "手冊",
    "建置",
    "驗收",
)
EXTRACTION_PIPELINE_VERSION = "2026-04-26-hybrid-context-v2"

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


def is_administrative_payment_text(text: str) -> bool:
    return any(marker in text for marker in ADMINISTRATIVE_WORK_ITEM_MARKERS)


def looks_like_task_item(text: str) -> bool:
    if is_administrative_payment_text(text):
        return False
    if is_payment_header(text) or SECTION_HEADING_PATTERN.search(text):
        return False
    return any(marker in text for marker in TASKISH_MARKERS) or len(text) <= 48


def stitch_paragraph_texts(paragraphs: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for paragraph in paragraphs:
        text = paragraph["text"].strip()
        if not text:
            continue
        if not parts:
            parts.append(text)
            continue
        previous = parts[-1]
        if previous.endswith(("總", "金", "價", "合", "第", "期", "款", "之")) and len(text) <= 40:
            parts[-1] = previous + text
        elif len(previous) <= 20 and not previous.endswith(("。", "；", "：", ":")) and len(text) <= 40:
            parts[-1] = f"{previous}{text}"
        else:
            parts.append(text)
    return " ".join(parts)


def trim_payment_clause_text(text: str) -> str:
    trimmed = text
    for marker in ("工作項目：", "工作項目:", "【備註】"):
        if marker in trimmed:
            trimmed = trimmed.split(marker, 1)[0].strip()
    return trimmed


def collect_related_paragraphs(paragraphs: list[dict[str, Any]], start_index: int, limit: int = 8) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for related_paragraph in paragraphs[start_index : start_index + limit]:
        if related_paragraph is not paragraphs[start_index] and is_payment_header(related_paragraph["text"]):
            break
        if related_paragraph is not paragraphs[start_index] and SECTION_HEADING_PATTERN.search(related_paragraph["text"]):
            break
        if related_paragraph is not paragraphs[start_index]:
            related_text = related_paragraph["text"].strip()
            if is_administrative_payment_text(related_text):
                break
            if WORK_ITEM_PATTERN.search(related_text) and extract_amount_from_text(related_text) is None and not PERCENT_PATTERN.search(related_text):
                break
        related.append(related_paragraph)
    return related


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
    collecting = False
    explicit_label = False
    implicit_mode = milestone_term_type(start_text) in {"工程節點", "phase"}
    for offset, paragraph in enumerate(paragraphs[start_index + 1 :], start=1):
        text = paragraph["text"].strip()
        if not text:
            if collecting:
                break
            continue
        if is_payment_header(text) or SECTION_HEADING_PATTERN.search(text):
            break
        if text.rstrip("：:") in WORK_ITEM_LABELS:
            collecting = True
            explicit_label = True
            continue
        if collecting and (
            text.startswith("【")
            or text.startswith("附件")
            or "付款比例" in text
            or "付款金額" in text
            or "付款時機" in text
            or "合計" in text
            or any(marker in text for marker in WORK_ITEM_STOP_MARKERS)
            or is_administrative_payment_text(text)
        ):
            break
        if not collecting:
            if WORK_ITEM_PATTERN.search(text):
                if is_administrative_payment_text(text):
                    break
                if offset <= 2 and (implicit_mode or looks_like_task_item(clean_work_item(text))):
                    collecting = True
                else:
                    break
            elif implicit_mode and offset <= 2 and looks_like_task_item(text):
                collecting = True
        if not collecting:
            continue
        if explicit_label and not WORK_ITEM_PATTERN.search(text) and not looks_like_task_item(text):
            break
        if WORK_ITEM_PATTERN.search(text) or explicit_label:
            if any(marker in text for marker in WORK_ITEM_STOP_MARKERS) and not WORK_ITEM_PATTERN.search(text):
                break
            cleaned = clean_work_item(text)
            if cleaned and not is_administrative_payment_text(cleaned):
                work_items.append(cleaned)
                continue
        if implicit_mode and looks_like_task_item(text) and not is_administrative_payment_text(text):
            work_items.append(text)
            continue
        if not explicit_label:
            break
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
        related_paragraphs = collect_related_paragraphs(paragraphs, offset)
        joined_text = stitch_paragraph_texts(related_paragraphs)
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
            if "驗收" in related_text and acceptance_criteria is None and "給付" not in related_text:
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
        normalized_joined_text = trim_payment_clause_text(joined_text)
        if amount is not None and any(token in normalized_joined_text for token in ("給付", "付款", "支付")) and len(normalized_joined_text) <= 300:
            payment_condition = normalized_joined_text
            milestone_citations.append(build_citation(source_file, paragraph, payment_condition, "milestone.payment_condition", "stitched_clause"))
        elif payment_condition is None and any(token in normalized_joined_text for token in ("給付", "付款", "支付")):
            payment_condition = normalized_joined_text[:300]
            milestone_citations.append(build_citation(source_file, paragraph, payment_condition, "milestone.payment_condition", "stitched_clause"))
        elif payment_condition and len(normalized_joined_text) <= 300:
            payment_condition = normalized_joined_text
        if acceptance_criteria is None and "驗收合格" in joined_text and len(joined_text) <= 300:
            acceptance_criteria = joined_text
            milestone_citations.append(build_citation(source_file, paragraph, acceptance_criteria, "milestone.acceptance_criteria", "stitched_clause"))
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
    installment_count = 0
    for paragraph in paragraphs:
        text = paragraph["text"]
        if is_payment_header(text) and (extract_amount_from_text(text) is not None or PERCENT_PATTERN.search(text)):
            installment_count += 1
    if installment_count >= 2:
        return "installment"
    joined = "\n".join(paragraph["text"] for paragraph in paragraphs)
    if "非分期付款" in joined or "一次付款" in joined or "一次性付款" in joined:
        if "保固保證金" in joined or "扣留" in joined:
            return "single_with_retention"
        return "single_payment"
    return "installment"


def has_explicit_retention_terms(text: str) -> bool:
    stripped = text.strip()
    if "無須繳納" in stripped:
        return False
    if "保固保證金" not in stripped:
        return False
    if "____" in stripped or "_____" in stripped or "     " in stripped:
        return False
    return extract_amount_from_text(stripped) is not None or PERCENT_PATTERN.search(stripped) is not None


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
        if retention is None and has_explicit_retention_terms(text):
            amount = extract_amount_from_text(text) or round(total_amount * 0.05)
            percent_match = PERCENT_PATTERN.search(text)
            retention = {
                "type": "retention",
                "amount": amount,
                "percentage": float(percent_match.group(1)) if percent_match else 5.0,
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


def build_initial_validation(
    *,
    source_file: str,
    active_paragraphs: list[dict[str, Any]],
    retired_paragraphs: list[dict[str, Any]],
    document_category: str,
    total_amount: int | None,
    milestones: list[dict[str, Any]],
    total_citations: list[dict[str, Any]],
    currency: str,
    currency_breakdown: list[dict[str, Any]],
    progress_checkpoints: list[dict[str, Any]],
    payment_type: str,
) -> list[dict[str, Any]]:
    validation: list[dict[str, Any]] = []
    if total_amount is None:
        validation.append({"code": "missing_total_amount", "severity": "WARNING", "message": "No total contract amount found; document may be an RFP or pre-award document.", "citations": []})
    if not milestones:
        validation.append({"code": "missing_milestones", "severity": "WARNING", "message": "No milestone blocks were extracted.", "citations": []})
    if not total_citations and total_amount is not None:
        validation.append({"code": "missing_total_citation", "severity": "ERROR", "message": "Total amount lacks a traceable citation.", "citations": []})
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
    return validation


def compute_confidence(total_amount: int | None, milestones: list[dict[str, Any]], extraction_method: str) -> int:
    confidence = 0
    if total_amount is not None:
        confidence += 40
    if milestones:
        confidence += 20
    if all(milestone["amount"] is not None for milestone in milestones) and milestones:
        confidence += 20
    if any(milestone["percentage"] is not None for milestone in milestones):
        confidence += 10
    if any(milestone["payment_condition"] for milestone in milestones):
        confidence += 10
    if extraction_method == "hybrid_llm":
        confidence = min(100, confidence + 5)
    return confidence


def build_locator_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    locator_blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    marker_map = {
        "total_amount": ("總價", "契約總價", "承攬總價", "工程總價", "合約總價"),
        "payment": ("付款", "請款", "給付", "期款"),
        "retention": ("保固保證金", "履約保證金", "扣留"),
        "version": ("V1", "V2", "修訂", "已廢除", "舊版"),
        "acceptance": ("驗收", "複驗", "查驗"),
        "checkpoint": ("查驗點",),
    }
    labeled_indices: set[int] = set()

    def labels_for_text(text: str) -> list[str]:
        labels: list[str] = []
        if is_payment_header(text):
            labels.append("milestone_header")
        if WORK_ITEM_PATTERN.search(text) or text.rstrip("：:") in WORK_ITEM_LABELS:
            labels.append("work_item")
        if extract_amount_from_text(text) is not None:
            labels.append("amount")
        if PERCENT_PATTERN.search(text):
            labels.append("percentage")
        for label, markers in marker_map.items():
            if any(marker in text for marker in markers):
                labels.append(label)
        return sorted(set(labels))

    for index, paragraph in enumerate(paragraphs):
        text = paragraph["text"].strip()
        if not text:
            continue
        labels = labels_for_text(text)
        if not labels:
            continue
        labeled_indices.update(range(max(0, index - 1), min(len(paragraphs), index + 3)))

    for index in sorted(labeled_indices):
        paragraph = paragraphs[index]
        text = paragraph["text"].strip()
        if not text or paragraph["block_id"] in seen:
            continue
        seen.add(paragraph["block_id"])
        labels = labels_for_text(text)
        if not labels:
            labels = ["context"]
        context_before = [item["text"] for item in paragraphs[max(0, index - 1) : index] if item["text"].strip()]
        context_after = [item["text"] for item in paragraphs[index + 1 : min(len(paragraphs), index + 3)] if item["text"].strip()]
        locator_blocks.append(
            {
                "block_id": paragraph["block_id"],
                "paragraph_index": paragraph["paragraph_index"],
                "page_estimate": paragraph["page_estimate"],
                "labels": sorted(set(labels)),
                "text": text[:400],
                "context_before": context_before[-1:] or [],
                "context_after": context_after[:2],
            }
        )
    return locator_blocks


def citations_from_block_ids(
    *,
    source_file: str,
    paragraph_map: dict[str, dict[str, Any]],
    block_ids: list[str],
    field_name: str,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block_id in block_ids:
        if block_id in seen or block_id not in paragraph_map:
            continue
        seen.add(block_id)
        paragraph = paragraph_map[block_id]
        citations.append(build_citation(source_file, paragraph, paragraph["text"][:200], field_name, "llm_locator"))
    return citations


def regex_fallback_extraction(document: dict[str, Any]) -> dict[str, Any]:
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
    if total_amount is None and not milestones and document["doc_category"] == "contract":
        document["doc_category"] = "rfp"
    validation = build_initial_validation(
        source_file=source_file,
        active_paragraphs=active_paragraphs,
        retired_paragraphs=retired_paragraphs,
        document_category=document["doc_category"],
        total_amount=total_amount,
        milestones=milestones,
        total_citations=total_citations,
        currency=currency,
        currency_breakdown=currency_breakdown,
        progress_checkpoints=progress_checkpoints,
        payment_type=payment_type,
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
        "extraction_method": "regex_fallback",
        "confidence": compute_confidence(total_amount, milestones, "regex_fallback"),
        "source_candidates": {"total_amount_candidates": total_candidates},
        "declared_installment_count": declared_installment_count,
        "blocks": build_blocks(paragraphs),
        "raw_text_preview": "\n".join(item["text"] for item in paragraphs[:20]),
        "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        **doc_notes,
    }


def merge_llm_extraction(
    *,
    document: dict[str, Any],
    regex_result: dict[str, Any],
    llm_result: dict[str, Any],
    locator_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    source_file = document["source_file"]
    paragraphs = document["paragraphs"]
    paragraph_map = {paragraph["block_id"]: paragraph for paragraph in paragraphs}
    regex_milestones = {milestone["source_order"]: milestone for milestone in regex_result["milestones"]}
    llm_milestones = llm_result.get("milestones") or [
        {
            "source_order": milestone["source_order"],
            "name": milestone["name"],
            "amount": milestone["amount"],
            "percentage": milestone["percentage"],
            "work_items": milestone["work_items"],
            "acceptance_criteria": milestone["acceptance_criteria"],
            "payment_condition": milestone["payment_condition"],
            "status": milestone["status"],
            "evidence": {},
        }
        for milestone in regex_result["milestones"]
    ]
    milestones: list[dict[str, Any]] = []
    for item in llm_milestones:
        fallback = regex_milestones.get(item["source_order"], {})
        evidence = item.get("evidence", {})
        milestone_citations = []
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("name_block_ids", []), field_name="milestone.name"))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("amount_block_ids", []), field_name="milestone.amount"))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("percentage_block_ids", []), field_name="milestone.percentage"))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("payment_block_ids", []), field_name="milestone.payment_condition"))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("acceptance_block_ids", []), field_name="milestone.acceptance_criteria"))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("work_item_block_ids", []), field_name="milestone.work_items"))
        if not milestone_citations:
            milestone_citations = fallback.get("citations", [])
        milestones.append(
            {
                "milestone_id": fallback.get("milestone_id", f"m_{uuid4().hex[:10]}"),
                "name": item["name"],
                "amount": item.get("amount"),
                "percentage": item.get("percentage"),
                "work_items": item.get("work_items") or fallback.get("work_items", []),
                "acceptance_criteria": item.get("acceptance_criteria") or fallback.get("acceptance_criteria"),
                "payment_condition": item.get("payment_condition") or fallback.get("payment_condition"),
                "status": item.get("status") or fallback.get("status", "pending_acceptance"),
                "citations": milestone_citations,
                "source_order": item["source_order"],
            }
        )
    total_citations = citations_from_block_ids(
        source_file=source_file,
        paragraph_map=paragraph_map,
        block_ids=llm_result.get("total_amount_block_ids", []),
        field_name="total_amount",
    ) or [citation for citation in regex_result["citations"] if citation["field_name"] == "total_amount"]
    progress_checkpoints = regex_result.get("progress_checkpoints", [])
    if llm_result.get("progress_checkpoints"):
        progress_checkpoints = []
        for item in llm_result["progress_checkpoints"]:
            progress_checkpoints.append(
                {
                    "name": item["name"],
                    "work_items": item.get("work_items", []),
                    "citations": citations_from_block_ids(
                        source_file=source_file,
                        paragraph_map=paragraph_map,
                        block_ids=item.get("evidence_block_ids", []),
                        field_name="progress_checkpoint.name",
                    ),
                    "source_order": item["source_order"],
                }
            )
    retention = regex_result.get("retention")
    if llm_result.get("retention"):
        retention = {
            "type": "retention",
            "amount": llm_result["retention"].get("amount"),
            "percentage": llm_result["retention"].get("percentage"),
            "release_condition": llm_result["retention"].get("release_condition"),
            "release_after_months": llm_result["retention"].get("release_after_months"),
            "citations": citations_from_block_ids(
                source_file=source_file,
                paragraph_map=paragraph_map,
                block_ids=llm_result["retention"].get("evidence_block_ids", []),
                field_name="retention",
            ),
        }
    doc_category = llm_result.get("doc_category") or regex_result["doc_category"]
    total_amount = llm_result.get("total_amount")
    if total_amount is None:
        total_amount = regex_result["total_amount"]
    if total_amount is None and not milestones and doc_category == "contract":
        doc_category = "rfp"
    currency = llm_result.get("currency") or regex_result["currency"]
    payment_type = llm_result.get("payment_type") or regex_result["payment_type"]
    contract_type = llm_result.get("contract_type") or regex_result["contract_type"]
    validation = build_initial_validation(
        source_file=source_file,
        active_paragraphs=live_paragraphs(paragraphs),
        retired_paragraphs=deprecated_paragraphs(paragraphs),
        document_category=doc_category,
        total_amount=total_amount,
        milestones=milestones,
        total_citations=total_citations,
        currency=currency,
        currency_breakdown=regex_result.get("currency_breakdown", []),
        progress_checkpoints=progress_checkpoints,
        payment_type=payment_type,
    )
    all_citations = total_citations + [citation for milestone in milestones for citation in milestone["citations"]]
    return {
        **regex_result,
        "total_amount": total_amount,
        "currency": currency,
        "contract_type": contract_type,
        "payment_type": payment_type,
        "doc_category": doc_category,
        "milestones": milestones,
        "retention": retention,
        "progress_checkpoints": progress_checkpoints,
        "citations": all_citations,
        "validation": validation,
        "extraction_method": "hybrid_llm",
        "confidence": compute_confidence(llm_result.get("total_amount"), milestones, "hybrid_llm"),
        "locator_blocks": locator_blocks,
        "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        "normalization": {"llm_attempted": True, "llm_applied": True},
    }


def extract_contract_data(document: dict[str, Any]) -> dict[str, Any]:
    regex_result = regex_fallback_extraction(document)
    regex_result["normalization"] = {"llm_attempted": False, "llm_applied": False}
    if document["doc_category"] == "construction_instruction":
        return regex_result
    locator_blocks = build_locator_blocks(document["paragraphs"])
    validation_hints = validate_contract_data(copy.deepcopy(regex_result))
    llm_result = extract_contract_with_llm(
        source_file=document["source_file"],
        doc_category=regex_result["doc_category"],
        locator_blocks=locator_blocks,
        regex_fallback={
            "doc_category": regex_result["doc_category"],
            "contract_type": regex_result["contract_type"],
            "payment_type": regex_result["payment_type"],
            "total_amount": regex_result["total_amount"],
            "currency": regex_result["currency"],
            "milestones": [
                {
                    "source_order": milestone["source_order"],
                    "name": milestone["name"],
                    "amount": milestone["amount"],
                    "percentage": milestone["percentage"],
                    "work_items": milestone["work_items"],
                    "acceptance_criteria": milestone["acceptance_criteria"],
                    "payment_condition": milestone["payment_condition"],
                    "status": milestone["status"],
                }
                for milestone in regex_result["milestones"]
            ],
            "retention": regex_result.get("retention"),
            "progress_checkpoints": regex_result.get("progress_checkpoints", []),
        },
        validation_issues=[{"code": item["code"], "severity": item["severity"], "message": item["message"]} for item in validation_hints],
    )
    if not llm_result:
        regex_result["locator_blocks"] = locator_blocks
        regex_result["normalization"] = {"llm_attempted": True, "llm_applied": False}
        return regex_result
    return merge_llm_extraction(document=document, regex_result=regex_result, llm_result=llm_result, locator_blocks=locator_blocks)


def serialize_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
