from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.config import settings
from backend.pipeline.llm import llm_available, query_local_llm_detailed

logger = logging.getLogger(__name__)
_LAST_LLM_ATTEMPT_META: dict[str, Any] = {
    "extraction_path": "regex_fallback",
    "fallback_reason": "none",
    "prompt_tokens": 0,
    "llm_ms": 0,
}

_MAX_LOCATOR_BLOCKS = 24
_MAX_MILESTONES = 8
_MAX_WORK_ITEMS = 3
_MAX_TEXT = 400
_MAX_CONTEXT_TEXT = 220
_MAX_TASK_PROMPT_TOKENS = 2800


def estimate_prompt_tokens(prompt: str) -> int:
    if not prompt:
        return 0
    cjk_chars = sum(1 for char in prompt if "\u3400" <= char <= "\u9fff")
    non_cjk_chars = len(prompt) - cjk_chars
    return max(1, cjk_chars + (non_cjk_chars // 4))


def get_last_llm_attempt_meta() -> dict[str, Any]:
    return dict(_LAST_LLM_ATTEMPT_META)


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        return int(cleaned) if cleaned.isdigit() else None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _extract_json_object(raw: str) -> dict[str, Any] | None:
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


def validate_llm_response_schema(parsed: dict[str, Any]) -> tuple[bool, str]:
    required_top_level = ["milestones"]
    for field in required_top_level:
        if field not in parsed:
            return False, f"missing_field:{field}"
    if not isinstance(parsed["milestones"], list):
        return False, "milestones_not_array"
    for index, milestone in enumerate(parsed["milestones"]):
        if not isinstance(milestone, dict):
            return False, f"milestone_{index}_not_object"
        if "name" not in milestone:
            return False, f"milestone_{index}_missing_name"
        if "amount" in milestone and milestone["amount"] is not None and not isinstance(milestone["amount"], (int, float)):
            return False, f"milestone_{index}_amount_wrong_type"
        if "percentage" in milestone and milestone["percentage"] is not None and not isinstance(milestone["percentage"], (int, float)):
            return False, f"milestone_{index}_percentage_wrong_type"
    return True, "ok"


def _coerce_block_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _normalize_milestones(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    milestones: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_order = _coerce_int(item.get("source_order"))
        name = _coerce_string(item.get("name"))
        if source_order is None or name is None:
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        milestones.append(
            {
                "source_order": source_order,
                "name": name,
                "amount": _coerce_int(item.get("amount")),
                "percentage": _coerce_float(item.get("percentage")),
                "work_items": _coerce_string_list(item.get("work_items")),
                "acceptance_criteria": _coerce_string(item.get("acceptance_criteria")),
                "payment_condition": _coerce_string(item.get("payment_condition")),
                "status": _coerce_string(item.get("status")) or "pending_acceptance",
                "evidence": {
                    "name_block_ids": _coerce_block_ids(evidence.get("name_block_ids")),
                    "amount_block_ids": _coerce_block_ids(evidence.get("amount_block_ids")),
                    "percentage_block_ids": _coerce_block_ids(evidence.get("percentage_block_ids")),
                    "work_item_block_ids": _coerce_block_ids(evidence.get("work_item_block_ids")),
                    "acceptance_block_ids": _coerce_block_ids(evidence.get("acceptance_block_ids")),
                    "payment_block_ids": _coerce_block_ids(evidence.get("payment_block_ids")),
                },
            }
        )
    return sorted(milestones, key=lambda item: item["source_order"])


def _normalize_progress_checkpoints(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    checkpoints: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        name = _coerce_string(item.get("name"))
        if not name:
            continue
        checkpoints.append(
            {
                "source_order": _coerce_int(item.get("source_order")) or index,
                "name": name,
                "work_items": _coerce_string_list(item.get("work_items")),
                "evidence_block_ids": _coerce_block_ids(item.get("evidence_block_ids")),
            }
        )
    return checkpoints


def _normalize_retention(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    amount = _coerce_int(value.get("amount"))
    percentage = _coerce_float(value.get("percentage"))
    if amount is None and percentage is None:
        return None
    return {
        "type": "retention",
        "amount": amount,
        "percentage": percentage,
        "release_condition": _coerce_string(value.get("release_condition")),
        "release_after_months": _coerce_int(value.get("release_after_months")),
        "evidence_block_ids": _coerce_block_ids(value.get("evidence_block_ids")),
    }


def _compact_regex_fallback(regex_fallback: dict[str, Any]) -> dict[str, Any]:
    milestones = []
    for item in regex_fallback.get("milestones", [])[:_MAX_MILESTONES]:
        if not isinstance(item, dict):
            continue
        milestones.append(
            {
                "source_order": item.get("source_order"),
                "name": item.get("name"),
                "amount": item.get("amount"),
                "percentage": item.get("percentage"),
                "work_items": list(item.get("work_items", []))[:_MAX_WORK_ITEMS],
                "acceptance_criteria": item.get("acceptance_criteria"),
                "payment_condition": item.get("payment_condition"),
                "status": item.get("status"),
            }
        )
    checkpoints = []
    for item in regex_fallback.get("progress_checkpoints", [])[:_MAX_MILESTONES]:
        if not isinstance(item, dict):
            continue
        checkpoints.append(
            {
                "source_order": item.get("source_order"),
                "name": item.get("name"),
                "work_items": list(item.get("work_items", []))[:_MAX_WORK_ITEMS],
            }
        )
    return {
        "doc_category": regex_fallback.get("doc_category"),
        "contract_type": regex_fallback.get("contract_type"),
        "payment_type": regex_fallback.get("payment_type"),
        "total_amount": regex_fallback.get("total_amount"),
        "currency": regex_fallback.get("currency"),
        "milestones": milestones,
        "retention": regex_fallback.get("retention"),
        "progress_checkpoints": checkpoints,
    }


def _compact_locator_blocks(locator_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    label_weights = {
        "milestone_header": 6,
        "total_amount": 5,
        "payment": 5,
        "amount": 4,
        "percentage": 4,
        "retention": 4,
        "acceptance": 3,
        "work_item": 3,
        "checkpoint": 3,
        "version": 2,
        "context": 1,
    }

    def score(item: dict[str, Any]) -> tuple[int, int]:
        labels = item.get("labels", [])
        weight = sum(label_weights.get(label, 0) for label in labels)
        return (-weight, int(item.get("paragraph_index", 0)))

    compacted: list[dict[str, Any]] = []
    for item in sorted(locator_blocks, key=score)[:_MAX_LOCATOR_BLOCKS]:
        compacted.append(
            {
                "block_id": item.get("block_id"),
                "paragraph_index": item.get("paragraph_index"),
                "page_estimate": item.get("page_estimate"),
                "labels": item.get("labels", []),
                "text": str(item.get("text", ""))[:_MAX_TEXT],
                "context_before": [str(part)[:_MAX_CONTEXT_TEXT] for part in item.get("context_before", [])[:1]],
                "context_after": [str(part)[:_MAX_CONTEXT_TEXT] for part in item.get("context_after", [])[:2]],
            }
        )
    return sorted(compacted, key=lambda item: int(item.get("paragraph_index", 0)))


def _prompt_payload(
    *,
    source_file: str,
    doc_category: str,
    locator_blocks: list[dict[str, Any]],
    regex_fallback: dict[str, Any],
    validation_issues: list[dict[str, Any]],
) -> str:
    del regex_fallback
    payload = {
        "source_file": source_file,
        "doc_category": doc_category,
        "task": "Extract a canonical contract structure directly from the located source evidence blocks.",
        "rules": [
            "Return JSON only. No markdown, no explanation.",
            "Use only the provided locator blocks. Do not infer facts from field names or examples.",
            "Regex was used only to locate possible evidence blocks; you are responsible for extraction.",
            "Prefer explicit phased payment schedules over optional alternatives.",
            "Do not convert blank guarantee templates into active retention amounts.",
            "Retention is not a normal milestone unless the document explicitly defines it as a payment stage.",
            "If the evidence is ambiguous, keep the field null instead of guessing.",
            "Every extracted field must point to locator block ids in the evidence object.",
            "payment_condition is the payment trigger or payment sentence; acceptance_criteria is the completion, approval, test, or acceptance requirement. Do not copy the same text into both unless the source only gives one mixed sentence.",
        ],
        "output_schema": {
            "doc_category": "contract|rfp|construction_instruction|null",
            "contract_type": "lump_sum|null",
            "payment_type": "installment|single_payment|single_with_retention|null",
            "total_amount": "int|null",
            "currency": "string|null",
            "total_amount_block_ids": ["block_id"],
            "milestones": [
                {
                    "source_order": "int",
                    "name": "string",
                    "amount": "int|null",
                    "percentage": "float|null",
                    "work_items": ["string"],
                    "acceptance_criteria": "string|null",
                    "payment_condition": "string|null",
                    "status": "string|null",
                    "evidence": {
                        "name_block_ids": ["block_id"],
                        "amount_block_ids": ["block_id"],
                        "percentage_block_ids": ["block_id"],
                        "work_item_block_ids": ["block_id"],
                        "acceptance_block_ids": ["block_id"],
                        "payment_block_ids": ["block_id"],
                    },
                }
            ],
            "retention": {
                "amount": "int|null",
                "percentage": "float|null",
                "release_condition": "string|null",
                "release_after_months": "int|null",
                "evidence_block_ids": ["block_id"],
            },
            "progress_checkpoints": [
                {
                    "source_order": "int|null",
                    "name": "string",
                    "work_items": ["string"],
                    "evidence_block_ids": ["block_id"],
                }
            ],
        },
        "validation_hints": validation_issues,
        "locator_blocks": _compact_locator_blocks(locator_blocks),
    }
    return json.dumps(payload, ensure_ascii=False)


def _format_source_blocks(blocks: list[dict[str, Any]], *, max_text: int = 360) -> str:
    lines: list[str] = []
    for block in blocks:
        block_id = block.get("block_id")
        text = str(block.get("text", "")).replace("\n", " ").strip()[:max_text]
        if block_id and text:
            lines.append(f"[{block_id}] {text}")
    return "\n".join(lines)


def _task_prompt(task: str, blocks: list[dict[str, Any]]) -> str:
    source = _format_source_blocks(blocks)
    if task == "total":
        return (
            "你是契約總價抽取器。只使用來源區塊；不可猜測。"
            "金額輸出整數，不含逗號；幣別用 TWD/NTD/USD/MULTI；未知填 null。"
            "只輸出 JSON。\n"
            '{"total_amount":null,"currency":null,"total_amount_block_ids":[]}\n'
            f"來源:\n{source}"
        )
    if task == "payment":
        return (
            "你是付款里程碑抽取器。只使用來源區塊；不可猜測；只輸出 JSON。"
            "抽取付款階段/期款/里程碑，不抽一般法律條款。"
            "若金額或百分比分在相鄰區塊，必須合併判讀。"
            "付款條件=含給付/付款/請款的句子；驗收條件=完成/核定/確認/驗收/測試通過條件。"
            "若無條列工作項目，從每期觸發條件提取短工作項目。"
            "金額整數不含逗號，百分比數字，未知 null。\n"
            '{"payment_type":null,"milestones":[{"source_order":1,"name":"","amount":null,"percentage":null,'
            '"work_items":[],"acceptance_criteria":null,"payment_condition":null,"status":"pending_acceptance",'
            '"evidence":{"name_block_ids":[],"amount_block_ids":[],"percentage_block_ids":[],"work_item_block_ids":[],'
            '"acceptance_block_ids":[],"payment_block_ids":[]}}],"progress_checkpoints":[]}\n'
            f"來源:\n{source}"
        )
    if task == "retention":
        return (
            "你是保證金/保留款抽取器。只使用來源區塊；不可猜測；只輸出 JSON。"
            "空白模板或明示無須繳納時 retention=null。"
            "只有明確扣留/保固保證金/退還條件才抽取。\n"
            '{"retention":null}\n'
            "或\n"
            '{"retention":{"amount":null,"percentage":null,"release_condition":null,"release_after_months":null,'
            '"evidence_block_ids":[]}}\n'
            f"來源:\n{source}"
        )
    if task == "version":
        return (
            "你是契約版本條款抽取器。只使用來源區塊；不可猜測；只輸出 JSON。"
            "辨識修訂、舊版、廢除、V1/V2，標示是否有版本衝突。\n"
            '{"has_version_conflict":false,"document_versions":[],"deprecated_block_ids":[]}\n'
            f"來源:\n{source}"
        )
    raise ValueError(f"Unsupported LLM extraction task: {task}")


def _call_json_task(task: str, blocks: list[dict[str, Any]], timeout: float = 180.0) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not blocks:
        return None, {"task": task, "status": "skipped", "fallback_reason": "no_blocks", "prompt_tokens": 0, "llm_ms": 0}
    prompt = _task_prompt(task, blocks)
    prompt_tokens = estimate_prompt_tokens(prompt)
    max_prompt_tokens = min(_MAX_TASK_PROMPT_TOKENS, max(1200, int(settings.local_model_num_ctx * 0.35)))
    if prompt_tokens > max_prompt_tokens:
        return None, {
            "task": task,
            "status": "fallback",
            "fallback_reason": f"prompt_too_large:{prompt_tokens}>{max_prompt_tokens}",
            "prompt_tokens": prompt_tokens,
            "llm_ms": 0,
        }

    started = time.perf_counter()
    llm_response = query_local_llm_detailed(prompt, timeout=timeout, response_format="json")
    llm_ms = int((time.perf_counter() - started) * 1000)
    raw = llm_response.get("response")
    error = llm_response.get("error")
    if error == "timeout":
        return None, {"task": task, "status": "fallback", "fallback_reason": "timeout", "prompt_tokens": prompt_tokens, "llm_ms": llm_ms}
    if not raw:
        fallback_reason = "empty_response" if error is None else error
        return None, {"task": task, "status": "fallback", "fallback_reason": fallback_reason, "prompt_tokens": prompt_tokens, "llm_ms": llm_ms}
    parsed = _extract_json_object(raw)
    if not parsed:
        return None, {"task": task, "status": "fallback", "fallback_reason": "invalid_json", "prompt_tokens": prompt_tokens, "llm_ms": llm_ms}
    return parsed, {"task": task, "status": "llm", "fallback_reason": "none", "prompt_tokens": prompt_tokens, "llm_ms": llm_ms}


def _task_allowed_block_ids(task_blocks: dict[str, list[dict[str, Any]]]) -> list[str]:
    allowed: list[str] = []
    seen: set[str] = set()
    for blocks in task_blocks.values():
        for block in blocks:
            block_id = block.get("block_id")
            if isinstance(block_id, str) and block_id not in seen:
                seen.add(block_id)
                allowed.append(block_id)
    return allowed


def extract_contract_with_llm(
    *,
    source_file: str,
    doc_category: str,
    locator_blocks: list[dict[str, Any]],
    regex_fallback: dict[str, Any],
    validation_issues: list[dict[str, Any]],
    task_blocks: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    global _LAST_LLM_ATTEMPT_META
    del locator_blocks, validation_issues

    if not llm_available():
        _LAST_LLM_ATTEMPT_META = {"extraction_path": "regex_fallback", "fallback_reason": "ollama_unavailable", "prompt_tokens": 0, "llm_ms": 0}
        return None

    task_blocks = task_blocks or {"payment": []}
    task_meta: list[dict[str, Any]] = []
    total_result, meta = _call_json_task("total", task_blocks.get("total", []))
    task_meta.append(meta)
    payment_result, meta = _call_json_task("payment", task_blocks.get("payment", []))
    task_meta.append(meta)
    retention_result, meta = _call_json_task("retention", task_blocks.get("retention", []))
    task_meta.append(meta)
    version_result, meta = _call_json_task("version", task_blocks.get("version", []), timeout=180.0)
    task_meta.append(meta)

    any_success = any(item["status"] == "llm" for item in task_meta)
    total_prompt_tokens = sum(int(item.get("prompt_tokens", 0)) for item in task_meta)
    total_llm_ms = sum(int(item.get("llm_ms", 0)) for item in task_meta)
    fallback_reasons = [f'{item["task"]}:{item["fallback_reason"]}' for item in task_meta if item.get("fallback_reason") != "none"]
    fallback_reason = ",".join(fallback_reasons) if fallback_reasons else "none"

    _LAST_LLM_ATTEMPT_META = {
        "extraction_path": "llm_tasks" if any_success else "regex_fallback",
        "fallback_reason": fallback_reason,
        "prompt_tokens": total_prompt_tokens,
        "llm_ms": total_llm_ms,
        "tasks": task_meta,
    }
    logger.info(
        "[EXTRACTION] file=%s | path=%s | prompt_tokens=%s | llm_ms=%s | fallback_reason=%s",
        source_file,
        "llm_tasks" if any_success else "regex_fallback",
        total_prompt_tokens,
        total_llm_ms,
        fallback_reason,
    )
    if not any_success:
        return None

    payment_result = payment_result or {}
    total_result = total_result or {}
    retention_result = retention_result or {}
    version_result = version_result or {}
    milestones = _normalize_milestones(payment_result.get("milestones"))
    total_amount = _coerce_int(total_result.get("total_amount"))
    return {
        "doc_category": doc_category,
        "contract_type": _coerce_string(regex_fallback.get("contract_type")) or "lump_sum",
        "payment_type": _coerce_string(payment_result.get("payment_type")),
        "total_amount": total_amount,
        "currency": _coerce_string(total_result.get("currency")),
        "total_amount_block_ids": _coerce_block_ids(total_result.get("total_amount_block_ids")),
        "milestones": milestones,
        "retention": _normalize_retention(retention_result.get("retention")),
        "progress_checkpoints": _normalize_progress_checkpoints(payment_result.get("progress_checkpoints")),
        "has_version_conflict": bool(version_result.get("has_version_conflict")) if isinstance(version_result, dict) else False,
        "_allowed_block_ids": _task_allowed_block_ids(task_blocks),
        "_meta": {
            "extraction_path": "llm_tasks",
            "fallback_reason": fallback_reason,
            "prompt_tokens": total_prompt_tokens,
            "llm_ms": total_llm_ms,
            "tasks": task_meta,
        },
    }
