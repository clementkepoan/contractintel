from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.config import settings


def audit_payload(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    issues: list[dict[str, Any]] = []
    block_map = {block.get("block_id"): block.get("text", "") for block in payload.get("blocks", [])}

    for milestone in payload.get("milestones", []):
        citations = milestone.get("citations", [])
        field_names = {citation.get("field_name") for citation in citations}

        for citation in citations:
            block_id = citation.get("block_id")
            text_snippet = citation.get("text_snippet") or ""
            source_text = block_map.get(block_id, "")
            citation_mode = citation.get("citation_mode", "exact_span")
            start = citation.get("char_offset_start", -1)
            end = citation.get("char_offset_end", -1)

            if block_id and block_id not in block_map:
                issues.append(
                    {
                        "path": path.name,
                        "milestone": milestone.get("source_order"),
                        "type": "missing_block",
                        "field_name": citation.get("field_name"),
                        "block_id": block_id,
                    }
                )
                continue

            if citation_mode == "exact_span":
                if text_snippet and source_text and text_snippet not in source_text:
                    issues.append(
                        {
                            "path": path.name,
                            "milestone": milestone.get("source_order"),
                            "type": "snippet_not_in_block",
                            "field_name": citation.get("field_name"),
                            "block_id": block_id,
                        }
                    )
                if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
                    issues.append(
                        {
                            "path": path.name,
                            "milestone": milestone.get("source_order"),
                            "type": "invalid_offsets",
                            "field_name": citation.get("field_name"),
                            "block_id": block_id,
                        }
                    )

        if milestone.get("payment_condition") and "milestone.payment_condition" not in field_names:
            issues.append(
                {
                    "path": path.name,
                    "milestone": milestone.get("source_order"),
                    "type": "missing_payment_citation",
                    "field_name": "milestone.payment_condition",
                }
            )
        if milestone.get("acceptance_criteria") and "milestone.acceptance_criteria" not in field_names:
            issues.append(
                {
                    "path": path.name,
                    "milestone": milestone.get("source_order"),
                    "type": "missing_acceptance_citation",
                    "field_name": "milestone.acceptance_criteria",
                }
            )
        if milestone.get("work_items") and "milestone.work_items" not in field_names:
            issues.append(
                {
                    "path": path.name,
                    "milestone": milestone.get("source_order"),
                    "type": "missing_work_items_citation",
                    "field_name": "milestone.work_items",
                }
            )
        if not milestone.get("acceptance_criteria") and "milestone.acceptance_criteria" in field_names:
            issues.append(
                {
                    "path": path.name,
                    "milestone": milestone.get("source_order"),
                    "type": "acceptance_citation_but_no_value",
                    "field_name": "milestone.acceptance_criteria",
                }
            )

    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit extracted citation integrity.")
    parser.add_argument("--file", type=str, help="Audit a single extracted JSON file.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.file:
        targets = [Path(args.file)]
    else:
        targets = sorted(settings.extracted_dir.glob("*.json"))

    issues: list[dict[str, Any]] = []
    for target in targets:
        issues.extend(audit_payload(target))

    summary = {"checked": len(targets), "issue_count": len(issues), "issues": issues}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    print(f"Checked {summary['checked']} extracted payloads")
    print(f"Issues: {summary['issue_count']}")
    for item in issues[:120]:
        print(
            f"{item['path']} | milestone={item.get('milestone')} | type={item['type']} | "
            f"field={item.get('field_name')} | block={item.get('block_id', '-')}"
        )


if __name__ == "__main__":
    main()
