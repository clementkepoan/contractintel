from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import delete
from fastapi import UploadFile
from sqlmodel import select

from backend.config import settings
from backend.db.models import Citation, Contract, IngestEvent, Milestone, ValidationWarning
from backend.pipeline.extractor import EXTRACTION_PIPELINE_VERSION, extract_contract_data, serialize_json
from backend.pipeline.indexer import write_chunk_index
from backend.pipeline.ingestion import compute_sha256, load_document, persist_upload
from backend.pipeline.validation import validate_contract_data
from backend.kg.graph import build_graph
from backend.wiki.generator import rebuild_contract_artifacts, resolve_contract_wiki_paths

logger = logging.getLogger(__name__)


def persist_extracted_json(contract_id: str, extracted: dict[str, Any]) -> Path:
    target = settings.extracted_dir / f"{contract_id}.json"
    target.write_text(serialize_json(extracted), encoding="utf-8")
    return target


def stable_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "contract"


def contract_key_from_source(source_file: str) -> str:
    return stable_slug(Path(source_file).stem)


def milestone_key_for(milestone: dict[str, Any]) -> str:
    return f"m{int(milestone.get('source_order') or 0):03d}"


def milestone_id_for(contract_id: str, milestone_key: str) -> str:
    return f"m_{uuid5(NAMESPACE_URL, f'{contract_id}:{milestone_key}').hex[:12]}"


def apply_stable_milestone_identity(contract_id: str, extracted: dict[str, Any]) -> None:
    for milestone in extracted["milestones"]:
        milestone_key = milestone_key_for(milestone)
        milestone["milestone_key"] = milestone_key
        milestone["milestone_id"] = milestone_id_for(contract_id, milestone_key)


def latest_contract_for_key(session: Any, contract_key: str) -> Contract | None:
    return session.exec(
        select(Contract)
        .where(Contract.contract_key == contract_key)
        .order_by(Contract.version_number.desc(), Contract.created_at.desc())
    ).first()


def active_contract_for_key(session: Any, contract_key: str) -> Contract | None:
    return session.exec(
        select(Contract)
        .where(Contract.contract_key == contract_key, Contract.is_superseded == False)  # noqa: E712
        .order_by(Contract.version_number.desc(), Contract.created_at.desc())
    ).first()


def load_milestone_rows_for_contract(session: Any, contract_id: str) -> list[Milestone]:
    return session.exec(select(Milestone).where(Milestone.contract_id == contract_id).order_by(Milestone.source_order)).all()


def write_ingest_event(
    session: Any,
    *,
    contract_key: str,
    contract_id: str | None,
    version_number: int,
    source_file: str,
    source_hash: str,
    action: str,
    diff: list[dict[str, Any]],
    pages: list[str],
) -> None:
    session.add(
        IngestEvent(
            event_id=f"ingest_{uuid4().hex[:12]}",
            contract_key=contract_key,
            contract_id=contract_id,
            version_number=version_number,
            source_file=source_file,
            source_hash=source_hash,
            action=action,
            diff_json=json.dumps(diff, ensure_ascii=False),
            created_pages_json=json.dumps(pages, ensure_ascii=False),
        )
    )


def expected_wiki_pages(contract_key: str, version_number: int, milestones: list[dict[str, Any]] | list[Milestone]) -> list[str]:
    pages = [
        f"contracts/{contract_key}.md",
        f"contract_versions/{contract_key}__v{version_number}.md",
        f"sources/{contract_key}__v{version_number}.md",
    ]
    for milestone in milestones:
        milestone_key = milestone["milestone_key"] if isinstance(milestone, dict) else milestone.milestone_key
        pages.append(f"milestones/{contract_key}__{milestone_key}.md")
        pages.append(f"milestone_versions/{contract_key}__{milestone_key}__v{version_number}.md")
    return pages


def _store_contract_children(session: Any, contract_id: str, extracted: dict[str, Any]) -> None:
    for milestone in extracted["milestones"]:
        session.add(
            Milestone(
                milestone_id=milestone["milestone_id"],
                milestone_key=milestone["milestone_key"],
                contract_id=contract_id,
                name=milestone["name"],
                source_order=milestone["source_order"],
                amount=milestone["amount"],
                percentage=milestone["percentage"],
                work_items_json=json.dumps(milestone["work_items"], ensure_ascii=False),
                acceptance_criteria=milestone["acceptance_criteria"],
                payment_condition=milestone["payment_condition"],
                status=milestone["status"],
                citations_json=json.dumps(milestone["citations"], ensure_ascii=False),
            )
        )
    for citation in extracted["citations"]:
        session.add(
            Citation(
                contract_id=contract_id,
                milestone_id=None,
                field_name=citation["field_name"],
                source_file=citation["source_file"],
                para_start=citation["para_start"],
                para_end=citation["para_end"],
                page_estimate=citation["page_estimate"],
                char_offset_start=citation["char_offset_start"],
                char_offset_end=citation["char_offset_end"],
                text_snippet=citation["text_snippet"],
                block_id=citation["block_id"],
                extraction_method=citation["extraction_method"],
                regex_pattern=citation["regex_pattern"],
            )
        )
    for milestone in extracted["milestones"]:
        for citation in milestone["citations"]:
            session.add(
                Citation(
                    contract_id=contract_id,
                    milestone_id=milestone["milestone_id"],
                    field_name=citation["field_name"],
                    source_file=citation["source_file"],
                    para_start=citation["para_start"],
                    para_end=citation["para_end"],
                    page_estimate=citation["page_estimate"],
                    char_offset_start=citation["char_offset_start"],
                    char_offset_end=citation["char_offset_end"],
                    text_snippet=citation["text_snippet"],
                    block_id=citation["block_id"],
                    extraction_method=citation["extraction_method"],
                    regex_pattern=citation["regex_pattern"],
                )
            )
    for warning in extracted["validation"]:
        session.add(
            ValidationWarning(
                contract_id=contract_id,
                code=warning["code"],
                severity=warning["severity"],
                message=warning["message"],
                citations_json=json.dumps(warning["citations"], ensure_ascii=False),
            )
        )


def _clear_contract_children(session: Any, contract_id: str) -> None:
    session.exec(delete(Citation).where(Citation.contract_id == contract_id))
    session.exec(delete(ValidationWarning).where(ValidationWarning.contract_id == contract_id))
    session.exec(delete(Milestone).where(Milestone.contract_id == contract_id))


def _store_contract(session: Any, extracted: dict[str, Any], source_file: str, source_hash: str, raw_json_path: Path) -> Contract:
    contract_id = f"c_{uuid4().hex[:10]}"
    contract_key = extracted.get("contract_key") or contract_key_from_source(source_file)
    version_number = int(extracted.get("version_number") or 1)
    apply_stable_milestone_identity(contract_id, extracted)
    contract = Contract(
        contract_id=contract_id,
        contract_key=contract_key,
        version_number=version_number,
        contract_name=extracted["contract_name"],
        source_file=source_file,
        doc_category=extracted["doc_category"],
        contract_type=extracted["contract_type"],
        currency=extracted["currency"],
        total_amount=extracted["total_amount"],
        total_amount_is_tax_included=extracted["total_amount_is_tax_included"],
        extraction_method=extracted["extraction_method"],
        status="active",
        validation_status=extracted["validation_status"],
        raw_json_path=str(raw_json_path),
        source_hash=source_hash,
    )
    session.add(contract)
    session.flush()
    _store_contract_children(session, contract.contract_id, extracted)
    session.commit()
    session.refresh(contract)
    return contract


def _contract_to_dict(session: Any, contract: Contract) -> dict[str, Any]:
    milestones = session.exec(select(Milestone).where(Milestone.contract_id == contract.contract_id).order_by(Milestone.source_order)).all()
    warnings = session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract.contract_id)).all()

    def attach_contract_context(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                **citation,
                "contract_id": contract.contract_id,
                "contract_key": contract.contract_key,
                "source_path": f"sources/{contract.contract_key}__v{contract.version_number}.md",
            }
            for citation in citations
        ]

    result = {
        "contract_id": contract.contract_id,
        "contract_key": contract.contract_key,
        "version_number": contract.version_number,
        "contract_name": contract.contract_name,
        "source_file": contract.source_file,
        "currency": contract.currency,
        "total_amount": contract.total_amount,
        "contract_type": contract.contract_type,
        "doc_category": contract.doc_category,
        "validation_status": contract.validation_status,
        "milestones": [],
        "validation": [],
    }
    for milestone in milestones:
        result["milestones"].append(
            {
                "milestone_id": milestone.milestone_id,
                "milestone_key": milestone.milestone_key,
                "name": milestone.name,
                "amount": milestone.amount,
                "percentage": milestone.percentage,
                "work_items": json.loads(milestone.work_items_json),
                "acceptance_criteria": milestone.acceptance_criteria,
                "payment_condition": milestone.payment_condition,
                "status": milestone.status,
                "citations": attach_contract_context(json.loads(milestone.citations_json)),
                "source_order": milestone.source_order,
            }
        )
    for warning in warnings:
        result["validation"].append(
            {
                "code": warning.code,
                "severity": warning.severity,
                "message": warning.message,
                "citations": attach_contract_context(json.loads(warning.citations_json)),
            }
        )
    return result


def resolve_source_block(session: Any, contract_id: str, block_id: str) -> dict[str, Any] | None:
    contract = session.get(Contract, contract_id)
    if not contract:
        return None
    payload = _load_payload(contract.raw_json_path)
    if not payload:
        return None
    for block in payload.get("blocks", []):
        if block.get("block_id") == block_id:
            return {
                "contract_id": contract.contract_id,
                "contract_key": contract.contract_key,
                "source_file": contract.source_file,
                "source_path": f"sources/{contract.contract_key}__v{contract.version_number}.md",
                "block_id": block.get("block_id"),
                "page_estimate": block.get("page_estimate"),
                "para_start": block.get("para_start"),
                "para_end": block.get("para_end"),
                "text": block.get("text"),
            }
    return None


def get_all_contracts(session: Any) -> list[dict[str, Any]]:
    contracts = session.exec(select(Contract).where(Contract.is_superseded == False).order_by(Contract.created_at.desc())).all()  # noqa: E712
    return [_contract_to_dict(session, contract) for contract in contracts]


def get_contract(session: Any, contract_id: str) -> dict[str, Any] | None:
    contract = session.get(Contract, contract_id)
    if not contract:
        return None
    return _contract_to_dict(session, contract)


def find_existing_contract(session: Any, source_file: str) -> Contract | None:
    return session.exec(
        select(Contract).where(Contract.source_file == source_file, Contract.is_superseded == False).order_by(Contract.created_at.desc())  # noqa: E712
    ).first()


def compute_version_conflicts(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    if not previous:
        return []
    conflicts: list[dict[str, Any]] = []
    top_fields = ["contract_name", "total_amount", "currency", "doc_category"]
    for field in top_fields:
        if previous.get(field) != current.get(field):
            conflicts.append({"field": field, "old": previous.get(field), "new": current.get(field)})
    previous_milestones = {item.get("milestone_key") or f"m{int(item.get('source_order') or 0):03d}": item for item in previous.get("milestones", [])}
    current_milestones = {item.get("milestone_key") or f"m{int(item.get('source_order') or 0):03d}": item for item in current.get("milestones", [])}
    for milestone_key, milestone in current_milestones.items():
        if milestone_key not in previous_milestones:
            conflicts.append({"field": f"milestones.{milestone_key}", "old": None, "new": milestone.get("name")})
            continue
        old = previous_milestones[milestone_key]
        for field in ["name", "amount", "percentage", "payment_condition"]:
            if old.get(field) != milestone.get(field):
                conflicts.append({"field": f"milestones.{milestone_key}.{field}", "old": old.get(field), "new": milestone.get(field)})
    for milestone_key, milestone in previous_milestones.items():
        if milestone_key not in current_milestones:
            conflicts.append({"field": f"milestones.{milestone_key}", "old": milestone.get("name"), "new": None})
    return conflicts


def _load_payload(path: Path | str) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _apply_contract_refresh(
    session: Any,
    *,
    contract: Contract,
    extracted: dict[str, Any],
    source_hash: str,
    action: str,
    version_conflicts: list[dict[str, Any]],
    old_revision: str | None,
) -> dict[str, Any]:
    raw_json_path = persist_extracted_json(contract.contract_id, extracted)
    contract.contract_name = extracted["contract_name"]
    contract.doc_category = extracted["doc_category"]
    contract.contract_type = extracted["contract_type"]
    contract.currency = extracted["currency"]
    contract.total_amount = extracted["total_amount"]
    contract.total_amount_is_tax_included = extracted["total_amount_is_tax_included"]
    contract.extraction_method = extracted["extraction_method"]
    contract.validation_status = extracted["validation_status"]
    contract.raw_json_path = str(raw_json_path)
    contract.source_hash = source_hash
    session.add(contract)
    _clear_contract_children(session, contract.contract_id)
    _store_contract_children(session, contract.contract_id, extracted)
    write_ingest_event(
        session,
        contract_key=contract.contract_key,
        contract_id=contract.contract_id,
        version_number=contract.version_number,
        source_file=contract.source_file,
        source_hash=source_hash,
        action=action,
        diff=version_conflicts,
        pages=expected_wiki_pages(contract.contract_key, contract.version_number, extracted["milestones"]),
    )
    session.commit()
    write_chunk_index(contract.contract_id, extracted)
    rebuild_contract_artifacts(
        session,
        latest_contract_id=contract.contract_id,
        source_file=contract.source_file,
        version_conflicts=version_conflicts,
        action=action,
    )
    build_graph(session)
    wiki_paths = resolve_contract_wiki_paths(session, contract.contract_id)
    logger.info(
        "[REPROCESS] file=%s | old_revision=%s | new_revision=%s | path=%s",
        contract.source_file,
        old_revision or "-",
        extracted.get("pipeline_revision", EXTRACTION_PIPELINE_VERSION),
        extracted.get("_meta", {}).get("extraction_path", extracted.get("extraction_method", "regex_fallback")),
    )
    return {
        "contract_id": contract.contract_id,
        "contract_key": contract.contract_key,
        "version_number": contract.version_number,
        "contract_name": contract.contract_name,
        "total_amount": contract.total_amount,
        "currency": contract.currency,
        "milestones_extracted": len(extracted["milestones"]),
        "validation_warnings": extracted["validation"],
        "citations_generated": len(extracted["citations"]) + sum(len(item["citations"]) for item in extracted["milestones"]),
        "wiki_updated": True,
        "ingest_action": action,
        "doc_category": extracted["doc_category"],
        "version_conflicts": version_conflicts,
        **wiki_paths,
    }


def ingest_upload(session: Any, upload: UploadFile) -> dict[str, Any]:
    persisted_path = persist_upload(upload)
    content = persisted_path.read_bytes()
    source_hash = compute_sha256(content)
    contract_key = contract_key_from_source(upload.filename)
    previous_contract = active_contract_for_key(session, contract_key)
    previous_payload = None
    if previous_contract:
        previous_path = Path(previous_contract.raw_json_path)
        if previous_path.exists():
            previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
    current_pipeline_revision = previous_payload.get("pipeline_revision") if previous_payload else None
    if previous_contract and previous_contract.source_hash == source_hash and current_pipeline_revision == EXTRACTION_PIPELINE_VERSION:
        write_ingest_event(
            session,
            contract_key=contract_key,
            contract_id=previous_contract.contract_id,
            version_number=previous_contract.version_number,
            source_file=upload.filename,
            source_hash=source_hash,
            action="noop",
            diff=[],
            pages=expected_wiki_pages(
                previous_contract.contract_key,
                previous_contract.version_number,
                load_milestone_rows_for_contract(session, previous_contract.contract_id),
            ),
        )
        session.commit()
        rebuild_contract_artifacts(
            session,
            latest_contract_id=previous_contract.contract_id,
            source_file=upload.filename,
            version_conflicts=[],
            action="noop",
        )
        wiki_paths = resolve_contract_wiki_paths(session, previous_contract.contract_id)
        return {
            "contract_id": previous_contract.contract_id,
            "contract_key": previous_contract.contract_key,
            "version_number": previous_contract.version_number,
            "contract_name": previous_contract.contract_name,
            "total_amount": previous_contract.total_amount,
            "currency": previous_contract.currency,
            "milestones_extracted": len(load_milestone_rows_for_contract(session, previous_contract.contract_id)),
            "validation_warnings": [],
            "citations_generated": 0,
            "wiki_updated": True,
            "ingest_action": "noop",
            "doc_category": previous_contract.doc_category,
            "version_conflicts": [],
            **wiki_paths,
        }
    document = load_document(persisted_path)
    extracted = extract_contract_data(document)
    validate_contract_data(extracted)
    contract_id = f"c_{uuid4().hex[:10]}"
    latest_contract = latest_contract_for_key(session, contract_key)
    version_number = (latest_contract.version_number + 1) if latest_contract else 1
    apply_stable_milestone_identity(contract_id, extracted)
    extracted["contract_key"] = contract_key
    extracted["version_number"] = version_number
    extracted["version_conflicts"] = compute_version_conflicts(previous_payload, extracted)
    raw_json_path = persist_extracted_json(contract_id, extracted)
    contract = Contract(
        contract_id=contract_id,
        contract_key=contract_key,
        version_number=version_number,
        contract_name=extracted["contract_name"],
        source_file=upload.filename,
        doc_category=extracted["doc_category"],
        contract_type=extracted["contract_type"],
        currency=extracted["currency"],
        total_amount=extracted["total_amount"],
        total_amount_is_tax_included=extracted["total_amount_is_tax_included"],
        extraction_method=extracted["extraction_method"],
        status="active",
        validation_status=extracted["validation_status"],
        raw_json_path=str(raw_json_path),
        source_hash=source_hash,
        source_version=f"v{version_number}",
        supersedes_contract_id=previous_contract.contract_id if previous_contract else None,
    )
    if previous_contract:
        previous_contract.is_superseded = True
        previous_contract.superseded_by_contract_id = contract.contract_id
        session.add(previous_contract)
    session.add(contract)
    for milestone in extracted["milestones"]:
        session.add(
            Milestone(
                milestone_id=milestone["milestone_id"],
                milestone_key=milestone["milestone_key"],
                contract_id=contract.contract_id,
                name=milestone["name"],
                source_order=milestone["source_order"],
                amount=milestone["amount"],
                percentage=milestone["percentage"],
                work_items_json=json.dumps(milestone["work_items"], ensure_ascii=False),
                acceptance_criteria=milestone["acceptance_criteria"],
                payment_condition=milestone["payment_condition"],
                status=milestone["status"],
                citations_json=json.dumps(milestone["citations"], ensure_ascii=False),
            )
        )
    for citation in extracted["citations"]:
        session.add(
            Citation(
                contract_id=contract.contract_id,
                milestone_id=None,
                field_name=citation["field_name"],
                source_file=citation["source_file"],
                para_start=citation["para_start"],
                para_end=citation["para_end"],
                page_estimate=citation["page_estimate"],
                char_offset_start=citation["char_offset_start"],
                char_offset_end=citation["char_offset_end"],
                text_snippet=citation["text_snippet"],
                block_id=citation["block_id"],
                extraction_method=citation["extraction_method"],
                regex_pattern=citation["regex_pattern"],
            )
        )
    for milestone in extracted["milestones"]:
        for citation in milestone["citations"]:
            session.add(
                Citation(
                    contract_id=contract.contract_id,
                    milestone_id=milestone["milestone_id"],
                    field_name=citation["field_name"],
                    source_file=citation["source_file"],
                    para_start=citation["para_start"],
                    para_end=citation["para_end"],
                    page_estimate=citation["page_estimate"],
                    char_offset_start=citation["char_offset_start"],
                    char_offset_end=citation["char_offset_end"],
                    text_snippet=citation["text_snippet"],
                    block_id=citation["block_id"],
                    extraction_method=citation["extraction_method"],
                    regex_pattern=citation["regex_pattern"],
                )
            )
    for warning in extracted["validation"]:
        session.add(
            ValidationWarning(
                contract_id=contract.contract_id,
                code=warning["code"],
                severity=warning["severity"],
                message=warning["message"],
                citations_json=json.dumps(warning["citations"], ensure_ascii=False),
            )
        )
    action = "updated" if previous_contract else "created"
    write_ingest_event(
        session,
        contract_key=contract_key,
        contract_id=contract.contract_id,
        version_number=version_number,
        source_file=upload.filename,
        source_hash=source_hash,
        action=action,
        diff=extracted["version_conflicts"],
        pages=expected_wiki_pages(contract_key, version_number, extracted["milestones"]),
    )
    session.commit()
    write_chunk_index(contract.contract_id, extracted)
    rebuild_contract_artifacts(
        session,
        latest_contract_id=contract.contract_id,
        source_file=upload.filename,
        version_conflicts=extracted["version_conflicts"],
        action=action,
    )
    build_graph(session)
    wiki_paths = resolve_contract_wiki_paths(session, contract.contract_id)
    citation_count = len(extracted["citations"]) + sum(len(item["citations"]) for item in extracted["milestones"])
    return {
        "contract_id": contract.contract_id,
        "contract_key": contract.contract_key,
        "version_number": contract.version_number,
        "contract_name": contract.contract_name,
        "total_amount": contract.total_amount,
        "currency": contract.currency,
        "milestones_extracted": len(extracted["milestones"]),
        "validation_warnings": extracted["validation"],
        "citations_generated": citation_count,
        "wiki_updated": True,
        "ingest_action": action,
        "doc_category": extracted["doc_category"],
        "version_conflicts": extracted["version_conflicts"],
        **wiki_paths,
    }


def reprocess_contract(
    session: Any,
    contract: Contract,
) -> dict[str, Any]:
    source_path = settings.uploads_dir / contract.source_file
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    content = source_path.read_bytes()
    source_hash = compute_sha256(content)
    previous_payload = _load_payload(contract.raw_json_path)
    old_revision = previous_payload.get("pipeline_revision") if previous_payload else None
    if source_hash == contract.source_hash and old_revision == EXTRACTION_PIPELINE_VERSION:
        logger.info(
            "[REPROCESS] file=%s | old_revision=%s | new_revision=%s | path=%s",
            contract.source_file,
            old_revision or "-",
            EXTRACTION_PIPELINE_VERSION,
            "skip",
        )
        return {"status": "skipped", "file": contract.source_file, "reason": "up_to_date"}
    document = load_document(source_path)
    extracted = extract_contract_data(document)
    validate_contract_data(extracted)
    apply_stable_milestone_identity(contract.contract_id, extracted)
    extracted["contract_key"] = contract.contract_key
    extracted["version_number"] = contract.version_number
    previous_contract = session.get(Contract, contract.supersedes_contract_id) if contract.supersedes_contract_id else None
    previous_version_payload = _load_payload(previous_contract.raw_json_path) if previous_contract else None
    extracted["version_conflicts"] = compute_version_conflicts(previous_version_payload, extracted)
    result = _apply_contract_refresh(
        session,
        contract=contract,
        extracted=extracted,
        source_hash=source_hash,
        action="reprocessed",
        version_conflicts=extracted["version_conflicts"],
        old_revision=old_revision,
    )
    return {"status": "processed", "file": contract.source_file, "result": result}


def reprocess_documents(
    session: Any,
    *,
    target: str,
    filename: str | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    contracts = session.exec(select(Contract).where(Contract.is_superseded == False).order_by(Contract.created_at.desc())).all()  # noqa: E712
    selected: list[Contract] = []
    if target == "all":
        selected = contracts
    elif target == "file":
        selected = [contract for contract in contracts if contract.source_file == filename]
    elif target == "since_revision":
        selected = [
            contract
            for contract in contracts
            if (_load_payload(contract.raw_json_path) or {}).get("pipeline_revision") != revision
        ]
    else:
        raise ValueError(f"Unsupported reprocess target: {target}")

    processed = 0
    failed: list[dict[str, str]] = []
    skipped: list[str] = []
    items: list[dict[str, Any]] = []
    if target == "file" and not selected and filename:
        failed.append({"file": filename, "error": "active_contract_not_found"})
        return {"processed": 0, "failed": failed, "skipped": [], "items": []}
    for contract in selected:
        try:
            outcome = reprocess_contract(session, contract)
            items.append(outcome)
            if outcome["status"] == "processed":
                processed += 1
            else:
                skipped.append(contract.source_file)
        except Exception as exc:
            failed.append({"file": contract.source_file, "error": str(exc)})
    return {"processed": processed, "failed": failed, "skipped": skipped, "items": items}
