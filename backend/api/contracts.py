from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import AcceptanceRecord, Contract, Milestone, Payment, PaymentRequest
from backend.pipeline.service import get_all_contracts, get_contract, resolve_source_block

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("")
def list_contracts() -> list[dict]:
    with get_session() as session:
        return get_all_contracts(session)


@router.get("/{contract_id}")
def contract_detail(contract_id: str) -> dict:
    with get_session() as session:
        contract = get_contract(session, contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found.")
        return contract


@router.get("/{contract_id}/raw")
def contract_raw(contract_id: str) -> dict:
    with get_session() as session:
        contract = session.get(Contract, contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found.")
        path = Path(contract.raw_json_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Extracted JSON not found.")
        return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{contract_id}/source-block/{block_id}")
def contract_source_block(contract_id: str, block_id: str) -> dict:
    with get_session() as session:
        source_block = resolve_source_block(session, contract_id, block_id)
        if not source_block:
            raise HTTPException(status_code=404, detail="Source block not found.")
        return source_block


@router.get("/{contract_id}/financials")
def contract_financials(contract_id: str) -> dict:
    with get_session() as session:
        contract = session.get(Contract, contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found.")
        milestones = session.exec(select(Milestone).where(Milestone.contract_id == contract_id)).all()
        requested = 0
        paid = 0
        for milestone in milestones:
            requests = session.exec(select(PaymentRequest).where(PaymentRequest.milestone_id == milestone.milestone_id)).all()
            requested += sum(item.requested_amount for item in requests)
            payments = session.exec(select(Payment).where(Payment.milestone_id == milestone.milestone_id)).all()
            paid += sum(item.paid_amount for item in payments)
        total = contract.total_amount or 0
        accepted_count = 0
        for milestone in milestones:
            accepted = session.exec(select(AcceptanceRecord).where(AcceptanceRecord.milestone_id == milestone.milestone_id, AcceptanceRecord.passed == True)).first()  # noqa: E712
            if accepted:
                accepted_count += 1
        return {
            "contract_id": contract.contract_id,
            "total_amount": total,
            "payment_requested": requested,
            "paid": paid,
            "unpaid": max(total - paid, 0),
            "accepted_milestones": accepted_count,
        }
