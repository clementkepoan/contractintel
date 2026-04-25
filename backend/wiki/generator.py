from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings


def slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "contract"


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_contract_page(contract: dict[str, Any]) -> str:
    rows = []
    for milestone in contract["milestones"]:
        rows.append(
            f"| {milestone['source_order']} | {milestone['name']} | {milestone['amount'] or 'N/A'} | {milestone['percentage'] or 'N/A'} | {milestone['status']} |"
        )
    warnings = contract.get("validation", [])
    warning_lines = ["- None"] if not warnings else [f"- {item['severity']}: {item['message']}" for item in warnings]
    contradiction_lines: list[str] = []
    for conflict in contract.get("version_conflicts", []):
        contradiction_lines.append(f"- {conflict['field']}: {conflict['old']} -> {conflict['new']}")
    header = []
    if contradiction_lines:
        header.extend(["## Contradictions", *contradiction_lines, ""])
    return "\n".join(
        [
            f"# {contract['contract_name']}",
            "",
            f"**Source:** {contract['source_file']}",
            f"**Total Amount:** {contract['total_amount'] or 'N/A'} {contract['currency']}",
            f"**Document Type:** {contract['doc_category']}",
            "",
            *header,
            "## Milestones",
            "| # | Name | Amount | % | Status |",
            "|---|---|---|---|---|",
            *rows,
            "",
            "## Validation",
            *warning_lines,
        ]
    )


def generate_milestone_page(contract: dict[str, Any], milestone: dict[str, Any]) -> str:
    citation_lines = []
    for citation in milestone["citations"]:
        citation_lines.append(
            f"> {citation['text_snippet']}\n> *{citation['source_file']}, Paragraph {citation['para_start']}, Page ~{citation['page_estimate']}*"
        )
    work_items = ["- None"] if not milestone["work_items"] else [f"- {item}" for item in milestone["work_items"]]
    return "\n".join(
        [
            f"# {milestone['name']}",
            "",
            f"**Contract:** {contract['contract_name']}",
            f"**Amount:** {milestone['amount'] or 'N/A'}",
            f"**Percentage:** {milestone['percentage'] or 'N/A'}",
            f"**Payment Condition:** {milestone['payment_condition'] or 'N/A'}",
            f"**Acceptance Criteria:** {milestone['acceptance_criteria'] or 'N/A'}",
            "",
            "## Work Items",
            *work_items,
            "",
            "## Citations",
            *citation_lines,
        ]
    )


def update_log(source_file: str, contract_name: str, validation: list[dict[str, Any]], version_conflicts: list[dict[str, Any]] | None = None) -> None:
    log_path = settings.wiki_dir / "log.md"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    validation_lines = ["- Validation: PASS"] if not validation else [f"- {item['severity']}: {item['message']}" for item in validation]
    entry = "\n".join(
        [
            f"## {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} - Ingested {source_file}",
            f"- Contract: {contract_name}",
            *validation_lines,
            *([f"- CONTRADICTION: {item['field']} {item['old']} -> {item['new']}" for item in (version_conflicts or [])]),
            "",
        ]
    )
    write_markdown(log_path, f"{entry}{existing}")


def regenerate_index(contracts: list[dict[str, Any]]) -> None:
    lines = [
        "# Contract Knowledge Base",
        "",
        f"Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Contract | Total Amount | Milestones | Status |",
        "|---|---|---|---|",
    ]
    for contract in contracts:
        slug = slugify(contract["contract_name"])
        lines.append(
            f"| [{contract['contract_name']}](contracts/{slug}.md) | {contract['total_amount'] or 'N/A'} | {len(contract['milestones'])} | {contract['validation_status']} |"
        )
    write_markdown(settings.wiki_dir / "index.md", "\n".join(lines))


def write_contract_artifacts(contract: dict[str, Any], all_contracts: list[dict[str, Any]]) -> None:
    slug = slugify(contract["contract_name"])
    write_markdown(settings.wiki_dir / "contracts" / f"{slug}.md", generate_contract_page(contract))
    for milestone in contract["milestones"]:
        write_markdown(settings.wiki_dir / "milestones" / f"{milestone['milestone_id']}.md", generate_milestone_page(contract, milestone))
    update_log(contract["source_file"], contract["contract_name"], contract.get("validation", []), contract.get("version_conflicts", []))
    regenerate_index(all_contracts)


def list_wiki_pages() -> list[str]:
    paths: list[str] = []
    for path in sorted(settings.wiki_dir.rglob("*.md")):
        paths.append(str(path.relative_to(settings.wiki_dir)))
    return paths


def read_wiki_page(relative_path: str) -> str:
    target = settings.wiki_dir / relative_path
    resolved = target.resolve()
    wiki_root = settings.wiki_dir.resolve()
    if not resolved.is_file() or wiki_root not in resolved.parents:
        raise FileNotFoundError(relative_path)
    return resolved.read_text(encoding="utf-8")
