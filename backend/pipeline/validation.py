from __future__ import annotations

from typing import Any


def validate_contract_data(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = list(extracted.get("validation", []))
    total_amount = extracted.get("total_amount")
    milestones = extracted.get("milestones", [])
    milestone_amounts = [item["amount"] for item in milestones if item.get("amount") is not None]
    milestone_percentages = [item["percentage"] for item in milestones if item.get("percentage") is not None]

    if total_amount is not None and milestone_amounts:
        milestone_sum = sum(milestone_amounts)
        delta = milestone_sum - total_amount
        if abs(delta) > 1:
            citations: list[dict[str, Any]] = []
            for milestone in milestones:
                if milestone.get("amount") is not None:
                    citations.extend([cite for cite in milestone["citations"] if cite["field_name"] == "milestone.amount"])
            warnings.append(
                {
                    "code": "amount_sum_mismatch",
                    "severity": "ERROR",
                    "message": f"Milestone amounts sum to {milestone_sum}, contract total is {total_amount}, delta = {delta:+}.",
                    "citations": citations[:8],
                }
            )

    if milestone_percentages:
        percent_sum = round(sum(milestone_percentages), 2)
        if percent_sum != 100.0:
            warnings.append(
                {
                    "code": "percentage_sum_mismatch",
                    "severity": "ERROR",
                    "message": f"Milestone percentages sum to {percent_sum}, expected 100.",
                    "citations": [],
                }
            )
    declared_installment_count = extracted.get("declared_installment_count")
    if declared_installment_count is not None and milestones and declared_installment_count != len(milestones):
        warnings.append(
            {
                "code": "installment_count_mismatch",
                "severity": "WARNING",
                "message": f"Document declares {declared_installment_count} payment installments but {len(milestones)} milestones were extracted.",
                "citations": [],
            }
        )
    if total_amount is not None and milestone_percentages:
        for milestone in milestones:
            amount = milestone.get("amount")
            percentage = milestone.get("percentage")
            if amount is None or percentage is None:
                continue
            expected_amount = round(total_amount * (percentage / 100))
            if abs(expected_amount - amount) > 1:
                implied_percentage = round((amount / total_amount) * 100, 1) if total_amount else 0
                warnings.append(
                    {
                        "code": "percentage_amount_inconsistency",
                        "severity": "ERROR",
                        "message": f'Milestone "{milestone["name"]}" states {percentage}% (expected {expected_amount}) but amount is {amount} (= {implied_percentage}%).',
                        "citations": milestone["citations"][:4],
                    }
                )

    seen_orders: set[int] = set()
    for milestone in milestones:
        order = milestone["source_order"]
        if order in seen_orders:
            warnings.append(
                {
                    "code": "duplicate_milestone_order",
                    "severity": "WARNING",
                    "message": f"Duplicate milestone order detected for order {order}.",
                    "citations": milestone["citations"][:2],
                }
            )
        seen_orders.add(order)
        if not milestone["citations"]:
            warnings.append(
                {
                    "code": "missing_milestone_citation",
                    "severity": "ERROR",
                    "message": f'Milestone "{milestone["name"]}" is missing citations.',
                    "citations": [],
                }
            )
        if not milestone.get("work_items"):
            warnings.append(
                {
                    "code": "missing_work_items",
                    "severity": "INFO",
                    "message": f'Milestone "{milestone["name"]}" has no extracted work items.',
                    "citations": milestone["citations"][:2],
                }
            )

    extracted["validation"] = warnings
    extracted["validation_status"] = "failed" if any(item["severity"] == "ERROR" for item in warnings) else "passed"
    return warnings
