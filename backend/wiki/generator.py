from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from sqlmodel import select

from backend.config import settings
from backend.db.models import Contract, FiledQuery, IngestEvent, Milestone, ValidationWarning
from backend.pipeline.llm import llm_available


def slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "contract"


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    lines = content.splitlines()
    metadata: dict[str, Any] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == "---":
            return metadata, "\n".join(lines[index + 1 :]).lstrip("\n")
        if ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            metadata[key] = raw_value
            index += 1
            continue
        index += 1
        items: list[str] = []
        while index < len(lines) and lines[index].startswith("  - "):
            items.append(lines[index][4:].strip())
            index += 1
        metadata[key] = items
    return metadata, content


def build_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def wiki_relative(path: Path) -> str:
    return path.relative_to(settings.wiki_dir).as_posix()


def markdown_link(from_path: Path, to_path: Path, label: str) -> str:
    return f"[{label}]({Path(os.path.relpath(to_path, from_path.parent)).as_posix()})"


def contract_page_path(contract_key: str) -> Path:
    return settings.wiki_dir / "contracts" / f"{contract_key}.md"


def contract_version_page_path(contract_key: str, version_number: int) -> Path:
    return settings.wiki_dir / "contract_versions" / f"{contract_key}__v{version_number}.md"


def source_page_path(contract: Contract) -> Path:
    return settings.wiki_dir / "sources" / f"{contract.contract_key}__v{contract.version_number}.md"


def milestone_page_path(contract_key: str, milestone_key: str) -> Path:
    return settings.wiki_dir / "milestones" / f"{contract_key}__{milestone_key}.md"


def milestone_version_page_path(contract_key: str, milestone_key: str, version_number: int) -> Path:
    return settings.wiki_dir / "milestone_versions" / f"{contract_key}__{milestone_key}__v{version_number}.md"


def query_page_path(query_id: str) -> Path:
    return settings.wiki_dir / "queries" / f"{query_id}.md"


def now_label() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def ensure_generated_dirs() -> None:
    for name in ["contracts", "contract_versions", "sources", "milestones", "milestone_versions", "queries"]:
        (settings.wiki_dir / name).mkdir(parents=True, exist_ok=True)


def reset_generated_dir(name: str) -> None:
    target = settings.wiki_dir / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def load_raw_payload(contract: Contract) -> dict[str, Any]:
    path = Path(contract.raw_json_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_raw_milestone(contract: Contract, milestone: Milestone) -> dict[str, Any] | None:
    payload = load_raw_payload(contract)
    milestones = payload.get("milestones", [])
    for item in milestones:
        if item.get("milestone_key") == milestone.milestone_key:
            return item
    for item in milestones:
        if item.get("source_order") == milestone.source_order:
            return item
    return None


def load_validation_rows(session: Any, contract_id: str) -> list[ValidationWarning]:
    return session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract_id)).all()


def load_milestone_rows(session: Any, contract_id: str) -> list[Milestone]:
    return session.exec(select(Milestone).where(Milestone.contract_id == contract_id).order_by(Milestone.source_order)).all()


def format_money(value: int | None, currency: str) -> str:
    return f"{value:,} {currency}" if value is not None else f"N/A {currency}"


def unique_lines(items: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def summarize_page(content: str) -> str:
    _, body = parse_frontmatter(content)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(">") or stripped.startswith("|"):
            continue
        return stripped[2:162] if stripped.startswith("- ") else stripped[:160]
    return ""


def related_source_paths(contracts: list[Contract]) -> list[str]:
    return [wiki_relative(source_page_path(contract)) for contract in contracts]


def maintain_with_local_llm(path: Path, generated: str, label: str) -> str:
    if not path.exists() or not llm_available():
        return generated
    existing = path.read_text(encoding="utf-8")
    if existing.strip() == generated.strip():
        return generated
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You maintain an offline contract wiki. Revise the existing markdown page using the new generated facts. "
                "Preserve YAML frontmatter, markdown links, citations, and tables. Do not invent facts. "
                "Flag contradictions explicitly instead of deleting them.",
            ),
            ("human", "Page: {label}\n\nExisting page:\n{existing}\n\nNew generated page:\n{generated}"),
        ]
    )
    chain = prompt | ChatOllama(model=settings.local_model_name, base_url=settings.local_model_base_url, temperature=0, num_ctx=settings.local_model_num_ctx) | StrOutputParser()
    try:
        revised = chain.invoke({"label": label, "existing": existing[:12000], "generated": generated[:12000]})
    except Exception:
        return generated
    return revised if revised.strip().startswith("---") else generated


def generate_contract_page(contract_key: str, contracts: list[Contract], session: Any, *, snapshot: bool = False) -> str:
    active_contract = next((item for item in contracts if not item.is_superseded), contracts[0])
    target_path = contract_version_page_path(contract_key, active_contract.version_number) if snapshot else contract_page_path(contract_key)
    active_milestones = load_milestone_rows(session, active_contract.contract_id)
    related = related_source_paths(contracts)
    related.append(wiki_relative(contract_version_page_path(contract_key, active_contract.version_number)))
    source_rows = []
    conflict_lines: list[str] = []
    note_lines: list[str] = []
    warning_lines: list[str] = []

    for contract in sorted(contracts, key=lambda item: item.version_number, reverse=True):
        source_path = source_page_path(contract)
        source_rows.append(
            f"| {contract.source_file} | v{contract.version_number} | {contract.doc_category} | {'active' if not contract.is_superseded else 'superseded'} | "
            f"{markdown_link(target_path, source_path, contract.contract_id)} |"
        )
        raw_payload = load_raw_payload(contract)
        for conflict in raw_payload.get("version_conflicts", []):
            conflict_lines.append(f"- v{contract.version_number} `{conflict['field']}` changed from `{conflict['old']}` to `{conflict['new']}`.")
        for note in raw_payload.get("scope_items", []) + raw_payload.get("acceptance_requirements", []) + raw_payload.get("safety_requirements", []):
            note_lines.append(f"- {note}")
        for warning in load_validation_rows(session, contract.contract_id):
            warning_lines.append(f"- v{contract.version_number} [{warning.severity}] {warning.message}")

    milestone_rows = []
    for milestone in active_milestones:
        raw_milestone = resolve_raw_milestone(active_contract, milestone) or {}
        milestone_path = milestone_page_path(contract_key, milestone.milestone_key)
        related.append(wiki_relative(milestone_path))
        milestone_rows.append(
            f"| {milestone.source_order} | {markdown_link(target_path, milestone_path, milestone.name)} | "
            f"{format_money(raw_milestone.get('amount', milestone.amount), active_contract.currency)} | "
            f"{raw_milestone.get('percentage', milestone.percentage) or 'N/A'} | {milestone.status} |"
        )

    metadata = build_frontmatter(
        {
            "kind": "contract_version" if snapshot else "contract",
            "title": active_contract.contract_name,
            "contract_key": contract_key,
            "contract_id": active_contract.contract_id,
            "version_number": active_contract.version_number,
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["contract", active_contract.doc_category, f"v{active_contract.version_number}"],
        }
    )
    return "\n".join(
        [
            metadata,
            "",
            f"# {active_contract.contract_name}",
            "",
            "## Snapshot",
            f"- Contract key: `{contract_key}`",
            f"- Current version: `v{active_contract.version_number}`",
            f"- Source documents tracked: {len(contracts)}",
            f"- Active source: `{active_contract.source_file}`",
            f"- Current total amount: {format_money(active_contract.total_amount, active_contract.currency)}",
            f"- Active milestone count: {len(active_milestones)}",
            "",
            "## Source Timeline",
            "| Source | Version | Type | State | Page |",
            "|---|---|---|---|---|",
            *(source_rows or ["| - | - | - | - | - |"]),
            "",
            "## Current Milestones",
            "| # | Milestone | Amount | % | Status |",
            "|---|---|---|---|---|",
            *(milestone_rows or ["| - | No milestone schedule extracted from the active source. | - | - | - |"]),
            "",
            "## Contradictions And Version Changes",
            *(unique_lines(conflict_lines) or ["- No version conflicts have been recorded yet."]),
            "",
            "## Maintained Synthesis",
            *(unique_lines(note_lines) or ["- No supporting technical or acceptance notes were extracted yet."]),
            "",
            "## Open Questions",
            *(unique_lines(warning_lines) or ["- No validation warnings are currently open."]),
        ]
    )


def generate_source_page(contract: Contract, milestones: list[Milestone], warnings: list[ValidationWarning]) -> str:
    target_path = source_page_path(contract)
    contract_path = contract_page_path(contract.contract_key)
    version_path = contract_version_page_path(contract.contract_key, contract.version_number)
    related = [wiki_relative(contract_path), wiki_relative(version_path)]
    related.extend(wiki_relative(milestone_page_path(contract.contract_key, item.milestone_key)) for item in milestones)
    raw_payload = load_raw_payload(contract)
    notes = []
    for section_name, label in (
        ("scope_items", "Scope"),
        ("acceptance_requirements", "Acceptance"),
        ("safety_requirements", "Safety"),
        ("warranty_requirements", "Warranty"),
    ):
        notes.extend(f"- **{label}:** {item}" for item in unique_lines(raw_payload.get(section_name, []), limit=4))
    validation_lines = [f"- [{warning.severity}] {warning.message}" for warning in warnings]
    conflict_lines = [f"- `{item['field']}` changed from `{item['old']}` to `{item['new']}`" for item in raw_payload.get("version_conflicts", [])]
    milestone_lines = [f"- {markdown_link(target_path, milestone_page_path(contract.contract_key, item.milestone_key), item.name)}" for item in milestones]
    metadata = build_frontmatter(
        {
            "kind": "source",
            "title": contract.source_file,
            "contract_key": contract.contract_key,
            "contract_id": contract.contract_id,
            "version_number": contract.version_number,
            "source_file": contract.source_file,
            "source_hash": contract.source_hash[:12],
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["source", contract.doc_category, f"v{contract.version_number}"],
        }
    )
    return "\n".join(
        [
            metadata,
            "",
            f"# Source: {contract.source_file}",
            "",
            "## Metadata",
            f"- Contract: {markdown_link(target_path, contract_path, contract.contract_name)}",
            f"- Version snapshot: {markdown_link(target_path, version_path, f'v{contract.version_number}')}",
            f"- Contract ID: `{contract.contract_id}`",
            f"- Source hash: `{contract.source_hash}`",
            f"- Document type: `{contract.doc_category}`",
            f"- Total amount: {format_money(contract.total_amount, contract.currency)}",
            "",
            "## Extracted Milestones",
            *(milestone_lines or ["- No milestone schedule was extracted from this source."]),
            "",
            "## Version Notes",
            *(conflict_lines or ["- This source did not introduce a tracked contradiction."]),
            "",
            "## Validation",
            *(validation_lines or ["- Validation passed without warnings."]),
            "",
            "## Notes",
            *(notes or ["- No structured technical notes were extracted from this source."]),
        ]
    )


def generate_milestone_page(contract: Contract, milestone: Milestone, *, snapshot: bool = False) -> str:
    target_path = (
        milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)
        if snapshot
        else milestone_page_path(contract.contract_key, milestone.milestone_key)
    )
    contract_path = contract_page_path(contract.contract_key)
    source_path = source_page_path(contract)
    raw_milestone = resolve_raw_milestone(contract, milestone) or {}
    citations = raw_milestone.get("citations") or json.loads(milestone.citations_json)
    ordered_citations: list[dict[str, Any]] = []
    seen_citations: set[tuple[str, str]] = set()
    citation_priority = {
        "milestone.name": 0,
        "milestone.amount": 1,
        "milestone.percentage": 2,
        "milestone.payment_condition": 3,
        "milestone.acceptance_criteria": 4,
        "milestone.work_items": 5,
    }
    for citation in sorted(citations, key=lambda item: (citation_priority.get(item.get("field_name", ""), 9), item.get("para_start", 0))):
        key = (str(citation.get("block_id", "")), str(citation.get("field_name", "")))
        if key in seen_citations:
            continue
        seen_citations.add(key)
        ordered_citations.append(citation)
    citation_lines = [
        f"> {citation['text_snippet']}\n> *{citation['source_file']}, paragraph {citation['para_start']}, page ~{citation['page_estimate']}*"
        for citation in ordered_citations
    ]
    work_items = raw_milestone.get("work_items") or json.loads(milestone.work_items_json)
    amount = raw_milestone.get("amount", milestone.amount)
    percentage = raw_milestone.get("percentage", milestone.percentage)
    payment_condition = raw_milestone.get("payment_condition", milestone.payment_condition)
    acceptance_criteria = raw_milestone.get("acceptance_criteria", milestone.acceptance_criteria)
    metadata = build_frontmatter(
        {
            "kind": "milestone_version" if snapshot else "milestone",
            "title": milestone.name,
            "contract_key": contract.contract_key,
            "contract_id": contract.contract_id,
            "milestone_key": milestone.milestone_key,
            "milestone_id": milestone.milestone_id,
            "version_number": contract.version_number,
            "updated_at": now_label(),
            "related": [wiki_relative(contract_path), wiki_relative(source_path)],
            "tags": ["milestone", contract.doc_category, milestone.status, f"v{contract.version_number}"],
        }
    )
    return "\n".join(
        [
            metadata,
            "",
            f"# {milestone.name}",
            "",
            "## Context",
            f"- Contract: {markdown_link(target_path, contract_path, contract.contract_name)}",
            f"- Source: {markdown_link(target_path, source_path, contract.source_file)}",
            f"- Milestone key: `{milestone.milestone_key}`",
            f"- Version: `v{contract.version_number}`",
            f"- Amount: {format_money(amount, contract.currency)}",
            f"- Percentage: {percentage or 'N/A'}",
            f"- Status: `{milestone.status}`",
            "",
            "## Terms",
            f"- Payment condition: {payment_condition or 'N/A'}",
            f"- Acceptance criteria: {acceptance_criteria or 'N/A'}",
            "",
            "## Work Items",
            *([f"- {item}" for item in work_items] or ["- No work items were extracted for this milestone."]),
            "",
            "## Citations",
            *(citation_lines or ["- No citations were stored for this milestone."]),
        ]
    )


def regenerate_log(session: Any) -> None:
    ingest_events = session.exec(select(IngestEvent).order_by(IngestEvent.created_at)).all()
    filed_queries = session.exec(select(FiledQuery).order_by(FiledQuery.created_at)).all()
    lines = [
        build_frontmatter({"kind": "log", "title": "Wiki Log", "updated_at": now_label(), "tags": ["log", "wiki"]}),
        "",
        "# Wiki Log",
        "",
    ]
    for event in ingest_events:
        diffs = json.loads(event.diff_json)
        pages = json.loads(event.created_pages_json)
        lines.extend(
            [
                f"## [{event.created_at.strftime('%Y-%m-%d %H:%M UTC')}] ingest | {event.source_file}",
                f"- Action: `{event.action}`",
                f"- Contract key: `{event.contract_key}`",
                f"- Contract ID: `{event.contract_id or '-'}`",
                f"- Version: `v{event.version_number}`",
                f"- Source hash: `{event.source_hash[:12]}`",
                *(f"- Page: `{page}`" for page in pages[:8]),
                *(f"- CONTRADICTION: `{item['field']}` {item['old']} -> {item['new']}" for item in diffs),
                "",
            ]
        )
    for filed in filed_queries:
        lines.extend(
            [
                f"## [{filed.created_at.strftime('%Y-%m-%d %H:%M UTC')}] query | {filed.query_id}",
                f"- Chat session: `{filed.chat_session_id}`",
                f"- Question: {filed.question}",
                f"- Wiki page: `{filed.wiki_path}`",
                "",
            ]
        )
    write_markdown(settings.wiki_dir / "log.md", "\n".join(lines))


def regenerate_index(session: Any) -> None:
    contracts = session.exec(select(Contract).order_by(Contract.contract_key, Contract.version_number.desc())).all()
    grouped: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.contract_key].append(contract)
    filed_queries = session.exec(select(FiledQuery).order_by(FiledQuery.created_at.desc())).all()
    lines = [
        build_frontmatter({"kind": "index", "title": "Repository Index", "updated_at": now_label(), "tags": ["index", "wiki"]}),
        "",
        "# Repository Index",
        "",
        "## Contracts",
    ]
    for contract_key, items in grouped.items():
        active = next((item for item in items if not item.is_superseded), items[0])
        lines.append(f"- [{active.contract_name}](contracts/{contract_key}.md) · `{contract_key}` · {len(items)} versions")
    lines.extend(["", "## Sources"])
    for contract in contracts:
        lines.append(f"- [{contract.source_file}](sources/{contract.contract_key}__v{contract.version_number}.md) · `{contract.contract_key}` · v{contract.version_number} · {contract.doc_category}")
    lines.extend(["", "## Query Notes"])
    if filed_queries:
        lines.extend(f"- [{item.question[:80]}]({item.wiki_path})" for item in filed_queries)
    else:
        lines.append("- No query notes have been filed yet.")
    lines.extend(["", "## Operations", "- [Wiki Log](log.md)"])
    write_markdown(settings.wiki_dir / "index.md", "\n".join(lines))


def pages_for_contract(contract: Contract, milestones: list[Milestone]) -> list[str]:
    pages = [
        wiki_relative(contract_page_path(contract.contract_key)),
        wiki_relative(contract_version_page_path(contract.contract_key, contract.version_number)),
        wiki_relative(source_page_path(contract)),
    ]
    for milestone in milestones:
        pages.append(wiki_relative(milestone_page_path(contract.contract_key, milestone.milestone_key)))
        pages.append(wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)))
    return pages


def rebuild_contract_artifacts(session: Any, latest_contract_id: str, source_file: str, version_conflicts: list[dict[str, Any]], action: str = "updated") -> list[str]:
    ensure_generated_dirs()
    for directory in ["contracts", "contract_versions", "sources", "milestones", "milestone_versions"]:
        reset_generated_dir(directory)

    contracts = session.exec(select(Contract).order_by(Contract.contract_key, Contract.version_number.desc())).all()
    grouped: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.contract_key].append(contract)

    written_pages: list[str] = []
    for contract_key, items in grouped.items():
        canonical_path = contract_page_path(contract_key)
        generated = generate_contract_page(contract_key, items, session)
        write_markdown(canonical_path, maintain_with_local_llm(canonical_path, generated, contract_key))
        written_pages.append(wiki_relative(canonical_path))
        for contract in items:
            version_path = contract_version_page_path(contract.contract_key, contract.version_number)
            write_markdown(version_path, generate_contract_page(contract.contract_key, [contract], session, snapshot=True))
            written_pages.append(wiki_relative(version_path))
            milestones = load_milestone_rows(session, contract.contract_id)
            source_path = source_page_path(contract)
            write_markdown(source_path, generate_source_page(contract, milestones, load_validation_rows(session, contract.contract_id)))
            written_pages.append(wiki_relative(source_path))
            for milestone in milestones:
                canonical_milestone = milestone_page_path(contract.contract_key, milestone.milestone_key)
                version_milestone = milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)
                if not contract.is_superseded:
                    write_markdown(canonical_milestone, generate_milestone_page(contract, milestone))
                    written_pages.append(wiki_relative(canonical_milestone))
                write_markdown(version_milestone, generate_milestone_page(contract, milestone, snapshot=True))
                written_pages.append(wiki_relative(version_milestone))

    regenerate_index(session)
    regenerate_log(session)
    return sorted(set(written_pages))


def append_query_note(
    *,
    session: Any,
    chat_session_id: str,
    contract_id: str | None,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
    answer_method: str,
    retrieval_mode: str,
) -> str:
    ensure_generated_dirs()
    query_id = f"query_{uuid4().hex[:12]}"
    path = query_page_path(query_id)
    related: list[str] = []
    if contract_id:
        contract = session.get(Contract, contract_id)
        if contract:
            related.extend([wiki_relative(contract_page_path(contract.contract_key)), wiki_relative(source_page_path(contract))])
    for citation in citations:
        for key in ("project_path", "source_path", "milestone_path"):
            if citation.get(key):
                related.append(citation[key])
    metadata = build_frontmatter(
        {
            "kind": "query",
            "title": query[:80],
            "query_id": query_id,
            "chat_session_id": chat_session_id,
            "contract_id": contract_id or "",
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["query", retrieval_mode],
        }
    )
    citation_lines = [
        f"- `{item.get('source_file')}` · block `{item.get('chunk_id') or item.get('block_id')}` · page ~{item.get('page_estimate')} · {item.get('text_snippet', '')[:180]}"
        for item in citations[:8]
    ]
    content = "\n".join(
        [
            metadata,
            "",
            f"# {query}",
            "",
            f"- Chat session: `{chat_session_id}`",
            f"- Answer method: `{answer_method}`",
            f"- Retrieval mode: `{retrieval_mode}`",
            "",
            "## Answer",
            answer,
            "",
            "## Evidence",
            *(citation_lines or ["- No evidence was attached."]),
        ]
    )
    write_markdown(path, content)
    session.add(
        FiledQuery(
            query_id=query_id,
            chat_session_id=chat_session_id,
            question=query,
            answer=answer,
            contract_scope_json=json.dumps([contract_id] if contract_id else [], ensure_ascii=False),
            citations_json=json.dumps(citations, ensure_ascii=False),
            wiki_path=wiki_relative(path),
        )
    )
    session.commit()
    regenerate_index(session)
    regenerate_log(session)
    return wiki_relative(path)


def build_wiki_manifest() -> dict[str, Any]:
    ensure_generated_dirs()
    pages: list[dict[str, Any]] = []
    for path in sorted(settings.wiki_dir.rglob("*.md")):
        relative = wiki_relative(path)
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        pages.append(
            {
                "path": relative,
                "kind": metadata.get("kind", "page"),
                "title": metadata.get("title") or path.stem,
                "summary": summarize_page(body),
                "updated_at": metadata.get("updated_at") or datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M UTC"),
                "tags": metadata.get("tags", []),
                "related": metadata.get("related", []),
            }
        )
    return {
        "pages": pages,
        "counts": {
            "total": len(pages),
            "contracts": sum(1 for item in pages if item["path"].startswith("contracts/")),
            "contract_versions": sum(1 for item in pages if item["path"].startswith("contract_versions/")),
            "sources": sum(1 for item in pages if item["path"].startswith("sources/")),
            "milestones": sum(1 for item in pages if item["path"].startswith("milestones/")),
            "milestone_versions": sum(1 for item in pages if item["path"].startswith("milestone_versions/")),
            "queries": sum(1 for item in pages if item["path"].startswith("queries/")),
        },
    }


def read_wiki_page(relative_path: str) -> dict[str, Any]:
    target = settings.wiki_dir / relative_path
    resolved = target.resolve()
    wiki_root = settings.wiki_dir.resolve()
    if not resolved.is_file() or wiki_root not in resolved.parents:
        raise FileNotFoundError(relative_path)
    content = resolved.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(content)
    manifest = build_wiki_manifest()["pages"]
    backlinks = [item for item in manifest if relative_path in item.get("related", [])]
    return {"path": relative_path, "content": body, "metadata": metadata, "backlinks": backlinks}


def resolve_contract_wiki_paths(session: Any, contract_id: str) -> dict[str, str]:
    contract = session.get(Contract, contract_id)
    if not contract:
        raise FileNotFoundError(contract_id)
    return {
        "contract_path": wiki_relative(contract_page_path(contract.contract_key)),
        "project_path": wiki_relative(contract_page_path(contract.contract_key)),
        "source_path": wiki_relative(source_page_path(contract)),
        "version_path": wiki_relative(contract_version_page_path(contract.contract_key, contract.version_number)),
    }


def resolve_milestone_wiki_path(session: Any, milestone_id: str) -> dict[str, str]:
    milestone = session.get(Milestone, milestone_id)
    if not milestone:
        raise FileNotFoundError(milestone_id)
    contract = session.get(Contract, milestone.contract_id)
    if not contract:
        raise FileNotFoundError(milestone_id)
    return {
        "milestone_path": wiki_relative(milestone_page_path(contract.contract_key, milestone.milestone_key)),
        "milestone_version_path": wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)),
    }


def run_wiki_lint(session: Any) -> dict[str, Any]:
    manifest = build_wiki_manifest()["pages"]
    page_paths = {item["path"] for item in manifest}
    findings: list[dict[str, str]] = []
    for page in manifest:
        for related in page.get("related", []):
            if related not in page_paths:
                findings.append({"severity": "warning", "page": page["path"], "message": f"Missing related page: {related}"})
        if page["kind"] in {"contract", "source", "milestone", "query"} and not page.get("related"):
            findings.append({"severity": "warning", "page": page["path"], "message": "Page has no related links in metadata."})
    for contract in session.exec(select(Contract)).all():
        expected = wiki_relative(source_page_path(contract))
        if expected not in page_paths:
            findings.append({"severity": "error", "page": expected, "message": "Missing source page for ingested contract."})
    for milestone in session.exec(select(Milestone)).all():
        contract = session.get(Contract, milestone.contract_id)
        if not contract:
            continue
        expected = wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number))
        if expected not in page_paths:
            findings.append({"severity": "error", "page": expected, "message": "Missing milestone version page."})
        if not json.loads(milestone.citations_json):
            findings.append({"severity": "warning", "page": expected, "message": "Milestone has no citations attached."})
    return {
        "status": "ok" if not any(item["severity"] == "error" for item in findings) else "warning",
        "findings": findings,
        "counts": build_wiki_manifest()["counts"],
    }
