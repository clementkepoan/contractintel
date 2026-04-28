from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any
from uuid import uuid4

from backend.config import settings
from backend.pipeline.extractor_llm import extract_contract_with_llm, get_last_llm_attempt_meta
from backend.pipeline.llm import llm_available, query_local_llm_detailed
from backend.pipeline.validation import validate_contract_data

logger = logging.getLogger(__name__)

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
PAYMENT_CONDITION_SIGNAL_PATTERN = re.compile(r"(?:甲方|客戶)?(?:應)?(?:給付|付款|支付|撥付|請款)")
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
ACCEPTANCE_MARKERS = (
    "驗收合格",
    "驗收通過",
    "經甲方驗收",
    "經客戶驗收",
    "測試通過",
    "功能測試",
    "檢測",
    "複驗",
)
EXTRACTION_PIPELINE_VERSION = "2026-04-27-citation-summary-v1"

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


def split_clause_units(text: str) -> list[str]:
    normalized = (
        text.replace("工作項目：", "。工作項目：")
        .replace("工作項目:", "。工作項目:")
        .replace("完成條件：", "。完成條件：")
        .replace("完成條件:", "。完成條件:")
        .replace("付款比例：", "。付款比例：")
        .replace("付款比例:", "。付款比例:")
        .replace("付款時機：", "。付款時機：")
        .replace("付款時機:", "。付款時機:")
    )
    chunks = re.split(r"[。\n；;]+", normalized)
    return [chunk.strip(" ，,:：") for chunk in chunks if chunk.strip(" ，,:：")]


def derive_milestone_terms(title: str, joined_text: str) -> tuple[str | None, str | None]:
    text = trim_payment_clause_text(joined_text)
    units = split_clause_units(text)
    payment_condition: str | None = None
    acceptance_criteria: str | None = None
    payment_index: int | None = None

    for index, unit in enumerate(units):
        if PAYMENT_CONDITION_SIGNAL_PATTERN.search(unit):
            payment_condition = unit[:300]
            payment_index = index
            break
    for index, unit in enumerate(units):
        if PAYMENT_CONDITION_SIGNAL_PATTERN.search(unit):
            continue
        if any(marker in unit for marker in ACCEPTANCE_MARKERS) or looks_like_task_item(unit):
            if payment_index is None or index <= payment_index:
                acceptance_criteria = unit[:300]
    if payment_condition and acceptance_criteria is None:
        prefix = re.split(PAYMENT_CONDITION_SIGNAL_PATTERN, payment_condition, maxsplit=1)[0].strip(" ，,:：")
        if prefix and prefix != title and (any(marker in prefix for marker in ACCEPTANCE_MARKERS) or looks_like_task_item(prefix)):
            acceptance_criteria = prefix[:300]
    if acceptance_criteria is None:
        title_trigger = re.sub(r"^(?:\[V\d修訂\]\s*)?第[一二三四五六七八九十\d]+期款?[：:、）)]?\s*", "", title).strip()
        if title_trigger and (
            any(marker in title_trigger for marker in ACCEPTANCE_MARKERS)
            or looks_like_task_item(title_trigger)
            or any(marker in title_trigger for marker in ("簽訂", "完成", "測試", "上線", "驗收"))
        ):
            acceptance_criteria = title_trigger[:300]
    if acceptance_criteria == payment_condition:
        acceptance_criteria = None
    return payment_condition, acceptance_criteria


def derive_work_items_from_trigger(title: str, payment_condition: str | None) -> list[str]:
    text = payment_condition or title
    text = re.sub(r"^(?:\[V\d修訂\]\s*)?第[一二三四五六七八九十\d]+期款?[：:、）)]?\s*", "", text).strip()
    text = re.split(r"[，,]?\s*(?:甲方|客戶)?(?:應)?(?:給付|付款|支付|撥付|請款)", text, maxsplit=1)[0].strip()
    text = text.replace("乙方", "").strip()
    text = re.sub(r"經(?:甲方|客戶|甲方及客戶|甲方與客戶)(?:核定|確認|驗收合格)後", "", text).strip()
    text = re.sub(r"經(?:甲方|客戶|甲方及客戶|甲方與客戶)(?:核定|確認|驗收合格)", "", text).strip()
    text = re.sub(r"後$", "", text).strip()
    if not text:
        return []
    if "驗收合格" in title and "驗收合格" not in text:
        text = f"{text}驗收合格"
    return [text[:120]]


def should_normalize_milestone_terms(
    title: str,
    payment_condition: str | None,
    acceptance_criteria: str | None,
    work_items: list[str],
) -> bool:
    combined_length = len(payment_condition or "") + len(acceptance_criteria or "") + sum(len(item) for item in work_items[:2])
    if combined_length < 180:
        return False
    if work_items and title[:12] in work_items[0]:
        return True
    if acceptance_criteria and title[:12] in acceptance_criteria:
        return True
    if payment_condition and title[:12] in payment_condition and any(marker in payment_condition for marker in ("驗收合格", "測試完成", "提出")):
        return True
    return False


def parse_json_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def keep_normalized_value(candidate: str | None, source_text: str, *, max_length: int = 220) -> str | None:
    if not isinstance(candidate, str):
        return None
    cleaned = candidate.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned if cleaned in source_text else None


def normalize_milestone_terms_with_llm(
    *,
    title: str,
    source_text: str,
    payment_condition: str | None,
    acceptance_criteria: str | None,
    work_items: list[str],
) -> tuple[list[str], str | None, str | None]:
    if not llm_available():
        return work_items, acceptance_criteria, payment_condition
    prompt = "\n".join(
        [
            "你是契約里程碑欄位正規化器。只可依據來源原文，使用繁體中文，輸出 JSON。",
            "目的：把同一長句拆成三種欄位，避免重複。",
            "規則：",
            "1. work_items 只保留交付/施工/測試/提交動作，不含付款語句。",
            "2. acceptance_criteria 只保留核定/確認/驗收/測試通過條件。",
            "3. payment_condition 保留可付款的完整條件與付款語句。",
            "4. 盡量直接摘錄來源原文片段，不要改寫同義句。",
            "5. 若來源沒有獨立驗收條件，可從同句中擷取最短可用片段。",
            "6. 只輸出 JSON，不要說明。",
            "",
            "範例1",
            "來源：功能整合款(20%)：乙方將附件一報價單項目一至十三之各項系統，整合至智慧建築管理平台，且智慧建築管理平台功能測試完成，並提出測試運轉紀錄文件，經甲方及客戶驗收合格後，甲方應給付工程總價20%予乙方。",
            '{"work_items":["整合至智慧建築管理平台","智慧建築管理平台功能測試完成","提出測試運轉紀錄文件"],"acceptance_criteria":"經甲方及客戶驗收合格後","payment_condition":"經甲方及客戶驗收合格後，甲方應給付工程總價20%予乙方"}',
            "",
            "範例2",
            "來源：第二期：乙方完成設備交貨，經甲方及客戶確認後，甲方應給付本契約總價30%予乙方。",
            '{"work_items":["完成設備交貨"],"acceptance_criteria":"經甲方及客戶確認後","payment_condition":"經甲方及客戶確認後，甲方應給付本契約總價30%予乙方"}',
            "",
            f"標題：{title}",
            f"來源原文：{source_text[:700]}",
            f"目前 work_items：{json.dumps(work_items, ensure_ascii=False)}",
            f"目前 acceptance_criteria：{acceptance_criteria or 'null'}",
            f"目前 payment_condition：{payment_condition or 'null'}",
            "",
            '輸出格式：{"work_items":[""],"acceptance_criteria":"","payment_condition":""}',
        ]
    )
    response = query_local_llm_detailed(prompt, timeout=180.0, response_format="json")
    parsed = parse_json_object(response.get("response"))
    if not parsed:
        return work_items, acceptance_criteria, payment_condition
    normalized_work_items: list[str] = []
    for item in parsed.get("work_items", []) if isinstance(parsed.get("work_items"), list) else []:
        kept = keep_normalized_value(item, source_text, max_length=120)
        if kept and kept not in normalized_work_items:
            normalized_work_items.append(kept)
    normalized_acceptance = keep_normalized_value(parsed.get("acceptance_criteria"), source_text, max_length=220)
    normalized_payment = keep_normalized_value(parsed.get("payment_condition"), source_text, max_length=260)
    return (
        normalized_work_items or work_items,
        normalized_acceptance or acceptance_criteria,
        normalized_payment or payment_condition,
    )


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
    amount, _snippet = extract_amount_evidence(text)
    return amount


def extract_amount_evidence(text: str) -> tuple[int | None, str | None]:
    match = AMOUNT_PATTERN.search(text)
    if match:
        return clean_number(match.group(1)), match.group(0)
    if any(marker in text for marker in ("給付", "付款", "金額", "保固保證金", "合約總價")):
        any_match = ANY_AMOUNT_PATTERN.search(text)
        if any_match:
            return clean_number(any_match.group(1) or any_match.group(2)), any_match.group(0)
    return None, None


def build_citation(
    source_file: str,
    paragraph: dict[str, Any],
    snippet: str,
    field_name: str,
    regex_pattern: str | None,
    citation_mode: str | None = None,
) -> dict[str, Any]:
    exact_index = paragraph["text"].find(snippet) if snippet else -1
    exact_match = exact_index >= 0
    return {
        "field_name": field_name,
        "source_file": source_file,
        "para_start": paragraph["paragraph_index"],
        "para_end": paragraph["paragraph_index"],
        "page_estimate": paragraph["page_estimate"],
        "char_offset_start": exact_index if exact_match else -1,
        "char_offset_end": (exact_index + len(snippet)) if exact_match else -1,
        "text_snippet": snippet[:300],
        "block_id": paragraph["block_id"],
        "citation_mode": citation_mode or ("exact_span" if exact_match else "block_support"),
        "extraction_method": "regex",
        "regex_pattern": regex_pattern,
    }


def find_paragraph_for_signals(
    paragraphs: list[dict[str, Any]],
    *,
    snippet: str | None = None,
    markers: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    snippet = (snippet or "").strip()
    for paragraph in paragraphs:
        text = paragraph["text"]
        if snippet and snippet in text:
            return paragraph
        if markers and any(marker in text for marker in markers):
            return paragraph
    return None


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


def build_segment_map(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    active_paragraphs = live_paragraphs(paragraphs)
    retired_paragraphs = deprecated_paragraphs(paragraphs)
    return {
        "active_paragraphs": active_paragraphs,
        "retired_paragraphs": retired_paragraphs,
        "payment_header_offsets": [index for index, paragraph in enumerate(active_paragraphs) if is_payment_header(paragraph["text"])],
        "checkpoint_offsets": [index for index, paragraph in enumerate(active_paragraphs) if CHECKPOINT_PATTERN.search(paragraph["text"])],
        "work_item_label_offsets": [index for index, paragraph in enumerate(active_paragraphs) if paragraph["text"].strip().rstrip("：:") in WORK_ITEM_LABELS],
        "amount_block_ids": [paragraph["block_id"] for paragraph in active_paragraphs if extract_amount_from_text(paragraph["text"]) is not None],
        "percentage_block_ids": [paragraph["block_id"] for paragraph in active_paragraphs if PERCENT_PATTERN.search(paragraph["text"])],
        "has_tax_included": any("含稅" in paragraph["text"] for paragraph in paragraphs),
        "deprecated_block_ids": [paragraph["block_id"] for paragraph in retired_paragraphs],
    }


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
        start_paragraph_index = related_paragraphs[0]["paragraph_index"]
        end_paragraph_index = related_paragraphs[-1]["paragraph_index"]
        for related in related_paragraphs:
            related_text = related["text"]
            parsed_amount, amount_snippet = extract_amount_evidence(related_text)
            if parsed_amount is not None and amount is None:
                amount = parsed_amount
                milestone_citations.append(build_citation(source_file, related, amount_snippet or str(parsed_amount), "milestone.amount", AMOUNT_PATTERN.pattern))
            percent_match = PERCENT_PATTERN.search(related_text)
            if percent_match and percentage is None:
                if related is paragraph or any(marker in related_text for marker in ("付款比例", "占合約總價", "合約總價之")):
                    percentage = float(percent_match.group(1))
                    milestone_citations.append(build_citation(source_file, related, percent_match.group(0), "milestone.percentage", PERCENT_PATTERN.pattern))
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
        payment_condition, acceptance_criteria = derive_milestone_terms(title, joined_text)
        work_items = extract_work_items(paragraphs, offset)
        work_items_derived = False
        if not work_items:
            work_items = derive_work_items_from_trigger(title, payment_condition)
            work_items_derived = bool(work_items)
        if should_normalize_milestone_terms(title, payment_condition, acceptance_criteria, work_items):
            normalized_work_items, normalized_acceptance_criteria, normalized_payment_condition = normalize_milestone_terms_with_llm(
                title=title,
                source_text=joined_text,
                payment_condition=payment_condition,
                acceptance_criteria=acceptance_criteria,
                work_items=work_items,
            )
            work_items = normalized_work_items
            acceptance_criteria = normalized_acceptance_criteria
            payment_condition = normalized_payment_condition
        payment_paragraph = find_paragraph_for_signals(
            related_paragraphs,
            snippet=payment_condition,
            markers=("給付", "付款", "支付", "請款"),
        )
        acceptance_paragraph = find_paragraph_for_signals(
            related_paragraphs,
            snippet=acceptance_criteria,
            markers=ACCEPTANCE_MARKERS,
        )
        work_item_paragraph = None
        if work_items and not work_items_derived:
            work_item_paragraph = find_paragraph_for_signals(
                related_paragraphs,
                snippet=work_items[0],
                markers=("工作項目",),
            )
        if payment_condition:
            milestone_citations.append(
                build_citation(
                    source_file,
                    payment_paragraph or paragraph,
                    payment_condition,
                    "milestone.payment_condition",
                    "stitched_clause",
                )
            )
        if acceptance_criteria:
            milestone_citations.append(
                build_citation(
                    source_file,
                    acceptance_paragraph or paragraph,
                    acceptance_criteria,
                    "milestone.acceptance_criteria",
                    "stitched_clause",
                )
            )
        if work_items:
            work_item_text = "\n".join(work_items)[:300]
            work_item_source = work_item_paragraph or paragraph
            work_item_snippet = work_item_source["text"][:200] if work_items_derived else work_item_text
            milestone_citations.append(
                build_citation(
                    source_file,
                    work_item_source,
                    work_item_snippet,
                    "milestone.work_items",
                    None,
                    citation_mode="derived_from_block" if work_items_derived else None,
                )
            )
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
                "start_paragraph_index": start_paragraph_index,
                "end_paragraph_index": end_paragraph_index,
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
        existing["start_paragraph_index"] = min(existing.get("start_paragraph_index", start_paragraph_index), start_paragraph_index)
        existing["end_paragraph_index"] = max(existing.get("end_paragraph_index", end_paragraph_index), end_paragraph_index)
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


def compact_task_block(paragraph: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": paragraph["block_id"],
        "paragraph_index": paragraph["paragraph_index"],
        "page_estimate": paragraph["page_estimate"],
        "text": paragraph["text"].strip(),
    }


def blocks_from_indices(paragraphs: list[dict[str, Any]], indices: set[int], *, limit: int, max_text: int = 420) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in sorted(indices):
        if index < 0 or index >= len(paragraphs):
            continue
        paragraph = paragraphs[index]
        text = paragraph["text"].strip()
        if not text or paragraph["block_id"] in seen:
            continue
        seen.add(paragraph["block_id"])
        block = compact_task_block(paragraph)
        block["text"] = block["text"][:max_text]
        blocks.append(block)
        if len(blocks) >= limit:
            break
    return blocks


def collect_until_next_section(paragraphs: list[dict[str, Any]], start: int, *, max_blocks: int) -> set[int]:
    indices: set[int] = set()
    for index in range(start, min(len(paragraphs), start + max_blocks)):
        if index != start and SECTION_HEADING_PATTERN.search(paragraphs[index]["text"]):
            break
        indices.add(index)
    return indices


def locate_total_task_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = ("總價", "契約總價", "承攬總價", "工程總價", "合約總價", "合約總額", "總額", "換算")
    for index, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        if SECTION_HEADING_PATTERN.search(text) and any(marker in text for marker in markers):
            return blocks_from_indices(paragraphs, collect_until_next_section(paragraphs, index, max_blocks=8), limit=8)
    indices: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        if is_payment_header(text) or ("%" in text and any(marker in text for marker in ("給付", "付款", "期款"))):
            continue
        if any(marker in text for marker in markers) and (
            extract_amount_from_text(text) is not None or re.search(r"新[臺台]幣|NTD|TWD|NT\$|USD|美元", text, re.IGNORECASE)
        ):
            indices.update(range(max(0, index - 1), min(len(paragraphs), index + 2)))
    return blocks_from_indices(paragraphs, indices, limit=10)


def locate_payment_task_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payment_section_markers = ("付款辦法", "付款方式", "請款及付款", "分期付款", "付款條件", "付款時機")
    indices: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        if any(marker in text for marker in payment_section_markers):
            indices.update(collect_until_next_section(paragraphs, max(0, index - 1), max_blocks=24))
        if is_payment_header(text):
            indices.update(range(max(0, index - 1), min(len(paragraphs), index + 4)))
    filtered: set[int] = set()
    for index in indices:
        text = paragraphs[index]["text"]
        if any(marker in text for marker in ("保密", "損害賠償", "不可抗力", "契約終止", "準據法")) and not any(
            marker in text for marker in payment_section_markers
        ):
            continue
        filtered.add(index)
    return blocks_from_indices(paragraphs, filtered, limit=24)


def locate_retention_task_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = ("保證金", "保固保證金", "履約保證金", "扣留", "保留款", "退還")
    for index, paragraph in enumerate(paragraphs):
        text = paragraph["text"]
        if SECTION_HEADING_PATTERN.search(text) and any(marker in text for marker in ("保證金", "保留款")):
            return blocks_from_indices(paragraphs, collect_until_next_section(paragraphs, index, max_blocks=10), limit=10)
    indices: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        if any(marker in paragraph["text"] for marker in markers):
            indices.update(range(max(0, index - 1), min(len(paragraphs), index + 3)))
    return blocks_from_indices(paragraphs, indices, limit=12)


def locate_version_task_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = ("V1", "V2", "V3", "修訂", "舊版", "廢除", "已廢除", "版本", "Version")
    indices: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        if any(marker in paragraph["text"] for marker in markers):
            indices.update(range(max(0, index - 1), min(len(paragraphs), index + 3)))
    return blocks_from_indices(paragraphs, indices, limit=14)


def build_llm_task_blocks(paragraphs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    active_paragraphs = live_paragraphs(paragraphs)
    return {
        "total": locate_total_task_blocks(active_paragraphs),
        "payment": locate_payment_task_blocks(active_paragraphs),
        "retention": locate_retention_task_blocks(active_paragraphs),
        "version": locate_version_task_blocks(paragraphs),
    }


def assemble_from_segment_map(
    segment_map: dict[str, Any],
    paragraphs: list[dict[str, Any]],
    *,
    source_file: str,
    document_category: str,
) -> dict[str, Any]:
    active_paragraphs = segment_map["active_paragraphs"]
    retired_paragraphs = segment_map["retired_paragraphs"]
    doc_notes = extract_document_notes(active_paragraphs, document_category)
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
    if total_amount is None and not milestones and document_category == "contract":
        document_category = "rfp"
    validation = build_initial_validation(
        source_file=source_file,
        active_paragraphs=active_paragraphs,
        retired_paragraphs=retired_paragraphs,
        document_category=document_category,
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
        "total_amount_is_tax_included": segment_map["has_tax_included"],
        "doc_category": document_category,
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
        "_meta": {
            "extraction_path": "regex_fallback",
            "fallback_reason": "none",
            "prompt_tokens": 0,
            "llm_ms": 0,
            "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        },
        "segment_map": {
            "payment_header_offsets": segment_map["payment_header_offsets"],
            "checkpoint_offsets": segment_map["checkpoint_offsets"],
            "work_item_label_offsets": segment_map["work_item_label_offsets"],
            "amount_block_ids": segment_map["amount_block_ids"],
            "percentage_block_ids": segment_map["percentage_block_ids"],
            "deprecated_block_ids": segment_map["deprecated_block_ids"],
        },
        **doc_notes,
    }


def citations_from_block_ids(
    *,
    source_file: str,
    paragraph_map: dict[str, dict[str, Any]],
    block_ids: list[str],
    field_name: str,
    allowed_block_ids: set[str] | None = None,
    milestone_start_idx: int | None = None,
    milestone_end_idx: int | None = None,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block_id in block_ids:
        if allowed_block_ids is not None and block_id not in allowed_block_ids:
            continue
        if block_id in seen or block_id not in paragraph_map:
            continue
        seen.add(block_id)
        paragraph = paragraph_map[block_id]
        paragraph_index = paragraph["paragraph_index"]
        if (
            milestone_start_idx is not None
            and milestone_end_idx is not None
            and not (milestone_start_idx <= paragraph_index <= milestone_end_idx)
        ):
            continue
        citations.append(build_citation(source_file, paragraph, paragraph["text"][:200], field_name, "llm_locator"))
    return citations


def dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (citation.get("field_name", ""), citation.get("block_id", ""), citation.get("text_snippet", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def choose_numeric_field(regex_value: int | float | None, llm_value: int | float | None) -> int | float | None:
    if regex_value is not None:
        return regex_value
    return llm_value


def llm_field_has_evidence(evidence: dict[str, Any], key: str) -> bool:
    value = evidence.get(key, [])
    return isinstance(value, list) and bool(value)


def looks_like_generic_milestone_name(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.fullmatch(r"(第[一二三四五六七八九十\d]+期|里程碑[一二三四五六七八九十A-Z\d]+|工程節點[一二三四五六七八九十\d]+)", value.strip()))


def choose_text_field(
    *,
    fallback_value: str | None,
    llm_value: str | None,
    has_llm_evidence: bool,
    allow_generic_override: bool = False,
) -> str | None:
    if fallback_value and not has_llm_evidence:
        return fallback_value
    if fallback_value and llm_value:
        if not allow_generic_override and looks_like_generic_milestone_name(llm_value) and len(fallback_value) > len(llm_value):
            return fallback_value
        return llm_value
    return llm_value or fallback_value


def regex_fallback_extraction(document: dict[str, Any]) -> dict[str, Any]:
    source_file = document["source_file"]
    paragraphs = document["paragraphs"]
    segment_map = build_segment_map(paragraphs)
    return assemble_from_segment_map(segment_map, paragraphs, source_file=source_file, document_category=document["doc_category"])


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
    llm_milestone_map = {milestone["source_order"]: milestone for milestone in (llm_result.get("milestones") or [])}
    allowed_block_ids = set(llm_result.get("_allowed_block_ids", [])) or None
    numeric_disagreement_warnings: list[dict[str, Any]] = []
    ignored_llm_orders: list[int] = []
    if regex_milestones:
        filtered_llm_milestone_map: dict[int, dict[str, Any]] = {}
        for order, milestone in llm_milestone_map.items():
            if order in regex_milestones:
                filtered_llm_milestone_map[order] = milestone
                continue
            ignored_llm_orders.append(order)
        llm_milestone_map = filtered_llm_milestone_map
    milestones: list[dict[str, Any]] = []
    milestone_orders = sorted(set(regex_milestones) | set(llm_milestone_map))
    if regex_milestones and len(llm_milestone_map) < len(regex_milestones):
        numeric_disagreement_warnings.append(
            {
                "code": "llm_partial_schedule_fallback",
                "severity": "WARNING",
                "message": f"LLM extracted only {len(llm_milestone_map)} milestones while regex extracted {len(regex_milestones)}; regex schedule completeness was preserved.",
                "citations": [],
            }
        )
    if ignored_llm_orders:
        numeric_disagreement_warnings.append(
            {
                "code": "llm_unmatched_milestones_ignored",
                "severity": "WARNING",
                "message": f"LLM returned unmatched milestone orders {ignored_llm_orders}; they were ignored because regex already defined the milestone schedule.",
                "citations": [],
            }
        )
    for order in milestone_orders:
        fallback = regex_milestones.get(order, {})
        item = llm_milestone_map.get(order) or {
            "source_order": order,
            "name": fallback.get("name"),
            "amount": fallback.get("amount"),
            "percentage": fallback.get("percentage"),
            "work_items": fallback.get("work_items", []),
            "acceptance_criteria": fallback.get("acceptance_criteria"),
            "payment_condition": fallback.get("payment_condition"),
            "status": fallback.get("status", "pending_acceptance"),
            "evidence": {},
        }
        evidence = item.get("evidence", {})
        milestone_start_idx = fallback.get("start_paragraph_index")
        milestone_end_idx = fallback.get("end_paragraph_index")
        if fallback.get("amount") is not None and item.get("amount") is not None and abs(fallback["amount"] - item["amount"]) > 1:
            numeric_disagreement_warnings.append(
                {
                    "code": "llm_regex_amount_disagreement",
                    "severity": "WARNING",
                    "message": f'Milestone "{fallback.get("name") or item["name"]}" LLM amount {item["amount"]} disagreed with regex amount {fallback["amount"]}; regex value was used.',
                    "citations": fallback.get("citations", [])[:2],
                }
            )
        if fallback.get("percentage") is not None and item.get("percentage") is not None and abs(fallback["percentage"] - item["percentage"]) > 0.01:
            numeric_disagreement_warnings.append(
                {
                    "code": "llm_regex_percentage_disagreement",
                    "severity": "WARNING",
                    "message": f'Milestone "{fallback.get("name") or item["name"]}" LLM percentage {item["percentage"]} disagreed with regex percentage {fallback["percentage"]}; regex value was used.',
                    "citations": fallback.get("citations", [])[:2],
                }
            )
        milestone_citations = list(fallback.get("citations", []))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("name_block_ids", []), field_name="milestone.name", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("amount_block_ids", []), field_name="milestone.amount", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("percentage_block_ids", []), field_name="milestone.percentage", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("payment_block_ids", []), field_name="milestone.payment_condition", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("acceptance_block_ids", []), field_name="milestone.acceptance_criteria", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations.extend(citations_from_block_ids(source_file=source_file, paragraph_map=paragraph_map, block_ids=evidence.get("work_item_block_ids", []), field_name="milestone.work_items", allowed_block_ids=allowed_block_ids, milestone_start_idx=milestone_start_idx, milestone_end_idx=milestone_end_idx))
        milestone_citations = dedupe_citations(milestone_citations)
        llm_name_has_evidence = llm_field_has_evidence(evidence, "name_block_ids")
        llm_payment_has_evidence = llm_field_has_evidence(evidence, "payment_block_ids")
        llm_acceptance_has_evidence = llm_field_has_evidence(evidence, "acceptance_block_ids")
        llm_work_items_have_evidence = llm_field_has_evidence(evidence, "work_item_block_ids")
        work_items = fallback.get("work_items", [])
        if item.get("work_items") and llm_work_items_have_evidence:
            work_items = item["work_items"]
        milestones.append(
            {
                "milestone_id": fallback.get("milestone_id", f"m_{uuid4().hex[:10]}"),
                "name": choose_text_field(
                    fallback_value=fallback.get("name"),
                    llm_value=item.get("name"),
                    has_llm_evidence=llm_name_has_evidence,
                ),
                "amount": choose_numeric_field(fallback.get("amount"), item.get("amount")),
                "percentage": choose_numeric_field(fallback.get("percentage"), item.get("percentage")),
                "work_items": work_items,
                "acceptance_criteria": choose_text_field(
                    fallback_value=fallback.get("acceptance_criteria"),
                    llm_value=item.get("acceptance_criteria"),
                    has_llm_evidence=llm_acceptance_has_evidence,
                    allow_generic_override=True,
                ),
                "payment_condition": choose_text_field(
                    fallback_value=fallback.get("payment_condition"),
                    llm_value=item.get("payment_condition"),
                    has_llm_evidence=llm_payment_has_evidence,
                    allow_generic_override=True,
                ),
                "status": item.get("status") or fallback.get("status", "pending_acceptance"),
                "citations": milestone_citations,
                "source_order": order,
                "start_paragraph_index": milestone_start_idx,
                "end_paragraph_index": milestone_end_idx,
            }
        )
    total_citations = citations_from_block_ids(
        source_file=source_file,
        paragraph_map=paragraph_map,
        block_ids=llm_result.get("total_amount_block_ids", []),
        field_name="total_amount",
        allowed_block_ids=allowed_block_ids,
    )
    if regex_result["total_amount"] is not None or not total_citations:
        total_citations = [citation for citation in regex_result["citations"] if citation["field_name"] == "total_amount"]
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
                        allowed_block_ids=allowed_block_ids,
                    ),
                    "source_order": item["source_order"],
                }
            )
    retention = regex_result.get("retention")
    if llm_result.get("retention") and not retention:
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
                allowed_block_ids=allowed_block_ids,
            ),
        }
    doc_category = llm_result.get("doc_category") or regex_result["doc_category"]
    total_amount = choose_numeric_field(regex_result["total_amount"], llm_result.get("total_amount"))
    if regex_result["total_amount"] is not None and llm_result.get("total_amount") is not None and abs(regex_result["total_amount"] - llm_result["total_amount"]) > 1:
        numeric_disagreement_warnings.append(
            {
                "code": "llm_regex_total_disagreement",
                "severity": "WARNING",
                "message": f'LLM total amount {llm_result["total_amount"]} disagreed with regex total amount {regex_result["total_amount"]}; regex value was used.',
                "citations": total_citations[:2],
            }
        )
    if total_amount is None and not milestones and doc_category == "contract":
        doc_category = "rfp"
    currency = regex_result["currency"] or llm_result.get("currency")
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
    validation.extend(numeric_disagreement_warnings)
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
        "confidence": compute_confidence(total_amount, milestones, "hybrid_llm"),
        "locator_blocks": locator_blocks,
        "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        "_meta": {
            "extraction_path": llm_result.get("_meta", {}).get("extraction_path", "llm_tasks"),
            "fallback_reason": llm_result.get("_meta", {}).get("fallback_reason", "none"),
            "prompt_tokens": llm_result.get("_meta", {}).get("prompt_tokens", 0),
            "llm_ms": llm_result.get("_meta", {}).get("llm_ms", 0),
            "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        },
        "normalization": {"llm_attempted": True, "llm_applied": True},
    }


def extract_contract_data(document: dict[str, Any]) -> dict[str, Any]:
    def log_extraction(result: dict[str, Any]) -> dict[str, Any]:
        meta = result.get("_meta", {})
        logger.info(
            "[EXTRACTION] file=%s | path=%s | prompt_tokens=%s | llm_ms=%s | fallback_reason=%s",
            document["source_file"],
            meta.get("extraction_path", "regex_fallback"),
            meta.get("prompt_tokens", 0),
            meta.get("llm_ms", 0),
            meta.get("fallback_reason", "none"),
        )
        return result

    regex_result = regex_fallback_extraction(document)
    regex_result["normalization"] = {"llm_attempted": False, "llm_applied": False}
    if document["doc_category"] == "construction_instruction":
        return log_extraction(regex_result)
    locator_blocks = build_locator_blocks(document["paragraphs"])
    task_blocks = build_llm_task_blocks(document["paragraphs"])
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
        task_blocks=task_blocks,
    )
    if not llm_result:
        regex_result["locator_blocks"] = locator_blocks
        regex_result["normalization"] = {"llm_attempted": True, "llm_applied": False}
        llm_meta = get_last_llm_attempt_meta()
        regex_result["_meta"] = {
            "extraction_path": "regex_fallback",
            "fallback_reason": llm_meta.get("fallback_reason", "empty_response"),
            "prompt_tokens": llm_meta.get("prompt_tokens", 0),
            "llm_ms": llm_meta.get("llm_ms", 0),
            "pipeline_revision": EXTRACTION_PIPELINE_VERSION,
        }
        return log_extraction(regex_result)
    merged = merge_llm_extraction(document=document, regex_result=regex_result, llm_result=llm_result, locator_blocks=locator_blocks)
    return log_extraction(merged)


def serialize_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
