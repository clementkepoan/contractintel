from __future__ import annotations

import json
from typing import Any

from backend.pipeline.llm import llm_available, query_local_llm

_MAX_LOCATOR_BLOCKS = 24
_MAX_MILESTONES = 8
_MAX_WORK_ITEMS = 3
_MAX_TEXT = 400
_MAX_CONTEXT_TEXT = 220


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
    payload = {
        "source_file": source_file,
        "doc_category": doc_category,
        "task": "Extract a canonical contract structure from located evidence blocks.",
        "rules": [
            "Return JSON only. No markdown, no explanation.",
            "Use only the provided locator blocks and regex fallback draft.",
            "Prefer explicit phased payment schedules over optional alternatives.",
            "Do not convert blank guarantee templates into active retention amounts.",
            "Retention is not a normal milestone unless the document explicitly defines it as a payment stage.",
            "If the evidence is ambiguous, keep the field null instead of guessing.",
            "Every extracted field must point to locator block ids in the evidence object.",
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
        "regex_fallback": _compact_regex_fallback(regex_fallback),
        "validation_issues": validation_issues,
        "locator_blocks": _compact_locator_blocks(locator_blocks),
    }
    return json.dumps(payload, ensure_ascii=False)


def extract_contract_with_llm(
    *,
    source_file: str,
    doc_category: str,
    locator_blocks: list[dict[str, Any]],
    regex_fallback: dict[str, Any],
    validation_issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not llm_available():
        return None
    prompt = _prompt_payload(
        source_file=source_file,
        doc_category=doc_category,
        locator_blocks=locator_blocks,
        regex_fallback=regex_fallback,
        validation_issues=validation_issues,
    )
    raw = query_local_llm(prompt, timeout=90.0)
    if not raw:
        return None
    parsed = _extract_json_object(raw)
    if not parsed:
        return None
    milestones = _normalize_milestones(parsed.get("milestones"))
    total_amount = _coerce_int(parsed.get("total_amount"))
    if total_amount is None and not milestones:
        return None
    return {
        "doc_category": _coerce_string(parsed.get("doc_category")),
        "contract_type": _coerce_string(parsed.get("contract_type")) or "lump_sum",
        "payment_type": _coerce_string(parsed.get("payment_type")),
        "total_amount": total_amount,
        "currency": _coerce_string(parsed.get("currency")),
        "total_amount_block_ids": _coerce_block_ids(parsed.get("total_amount_block_ids")),
        "milestones": milestones,
        "retention": _normalize_retention(parsed.get("retention")),
        "progress_checkpoints": _normalize_progress_checkpoints(parsed.get("progress_checkpoints")),
    }
