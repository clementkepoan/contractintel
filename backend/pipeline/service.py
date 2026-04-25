from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import select

from backend.config import settings
from backend.db.models import Citation, Contract, Milestone, ValidationWarning
from backend.pipeline.extractor import extract_contract_data, serialize_json
from backend.pipeline.indexer import write_chunk_index
from backend.pipeline.ingestion import compute_sha256, load_document, persist_upload
from backend.pipeline.validation import validate_contract_data
from backend.kg.graph import build_graph
from backend.wiki.generator import write_contract_artifacts


def persist_extracted_json(contract_id: str, extracted: dict[str, Any]) -> Path:
    target = settings.extracted_dir / f"{contract_id}.json"
    target.write_text(serialize_json(extracted), encoding="utf-8")
    return target


def _store_contract(session: Any, extracted: dict[str, Any], source_file: str, source_hash: str, raw_json_path: Path) -> Contract:
    contract_id = f"c_{uuid4().hex[:10]}"
    contract = Contract(
        contract_id=contract_id,
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
    for milestone in extracted["milestones"]:
        session.add(
            Milestone(
                milestone_id=milestone["milestone_id"],
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
    session.commit()
    session.refresh(contract)
    return contract


def _contract_to_dict(session: Any, contract: Contract) -> dict[str, Any]:
    milestones = session.exec(select(Milestone).where(Milestone.contract_id == contract.contract_id).order_by(Milestone.source_order)).all()
    warnings = session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract.contract_id)).all()
    result = {
        "contract_id": contract.contract_id,
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
                "name": milestone.name,
                "amount": milestone.amount,
                "percentage": milestone.percentage,
                "work_items": json.loads(milestone.work_items_json),
                "acceptance_criteria": milestone.acceptance_criteria,
                "payment_condition": milestone.payment_condition,
                "status": milestone.status,
                "citations": json.loads(milestone.citations_json),
                "source_order": milestone.source_order,
            }
        )
    for warning in warnings:
        result["validation"].append(
            {
                "code": warning.code,
                "severity": warning.severity,
                "message": warning.message,
                "citations": json.loads(warning.citations_json),
            }
        )
    return result


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
    previous_milestones = previous.get("milestones", [])
    current_milestones = current.get("milestones", [])
    for index, milestone in enumerate(current_milestones):
        if index >= len(previous_milestones):
            conflicts.append({"field": f"milestones[{index}]", "old": None, "new": milestone.get("name")})
            continue
        old = previous_milestones[index]
        for field in ["name", "amount", "percentage", "payment_condition"]:
            if old.get(field) != milestone.get(field):
                conflicts.append({"field": f"milestones[{index}].{field}", "old": old.get(field), "new": milestone.get(field)})
    return conflicts


def ingest_upload(session: Any, upload: UploadFile) -> dict[str, Any]:
    persisted_path = persist_upload(upload)
    content = persisted_path.read_bytes()
    source_hash = compute_sha256(content)
    document = load_document(persisted_path)
    extracted = extract_contract_data(document)
    validate_contract_data(extracted)
    previous_contract = find_existing_contract(session, upload.filename)
    previous_payload = None
    if previous_contract:
        previous_path = Path(previous_contract.raw_json_path)
        if previous_path.exists():
            previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
    extracted["version_conflicts"] = compute_version_conflicts(previous_payload, extracted)
    contract_id = f"c_{uuid4().hex[:10]}"
    raw_json_path = persist_extracted_json(contract_id, extracted)
    contract = Contract(
        contract_id=contract_id,
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
        source_version=f"v{2 if previous_contract else 1}",
        supersedes_contract_id=previous_contract.contract_id if previous_contract else None,
    )
    if previous_contract:
        previous_contract.is_superseded = True
        session.add(previous_contract)
    session.add(contract)
    for milestone in extracted["milestones"]:
        session.add(
            Milestone(
                milestone_id=milestone["milestone_id"],
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
    session.commit()
    write_chunk_index(contract.contract_id, extracted)
    all_contracts = get_all_contracts(session)
    contract_dict = next(item for item in all_contracts if item["contract_id"] == contract.contract_id)
    contract_dict["source_file"] = upload.filename
    contract_dict["version_conflicts"] = extracted["version_conflicts"]
    write_contract_artifacts(contract_dict, all_contracts)
    build_graph(session)
    citation_count = len(extracted["citations"]) + sum(len(item["citations"]) for item in extracted["milestones"])
    return {
        "contract_id": contract.contract_id,
        "contract_name": contract.contract_name,
        "total_amount": contract.total_amount,
        "currency": contract.currency,
        "milestones_extracted": len(extracted["milestones"]),
        "validation_warnings": extracted["validation"],
        "citations_generated": citation_count,
        "wiki_updated": True,
        "doc_category": extracted["doc_category"],
        "version_conflicts": extracted["version_conflicts"],
    }
