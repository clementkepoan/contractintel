from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import AcceptanceRecord, Contract, Milestone

router = APIRouter(prefix="/api/milestones", tags=["milestones"])


@router.get("/{milestone_id}")
def milestone_detail(milestone_id: str) -> dict:
    with get_session() as session:
        milestone = session.get(Milestone, milestone_id)
        if not milestone:
            raise HTTPException(status_code=404, detail="Milestone not found.")
        contract = session.get(Contract, milestone.contract_id)
        citations = json.loads(milestone.citations_json)
        if contract:
            citations = [
                {
                    **citation,
                    "contract_id": contract.contract_id,
                    "contract_key": contract.contract_key,
                    "source_path": f"sources/{contract.contract_key}__v{contract.version_number}.md",
                }
                for citation in citations
            ]
        return {
            "milestone_id": milestone.milestone_id,
            "contract_id": milestone.contract_id,
            "name": milestone.name,
            "amount": milestone.amount,
            "percentage": milestone.percentage,
            "work_items": json.loads(milestone.work_items_json),
            "acceptance_criteria": milestone.acceptance_criteria,
            "payment_condition": milestone.payment_condition,
            "status": milestone.status,
            "citations": citations,
        }


@router.get("/{milestone_id}/status")
def milestone_status(milestone_id: str) -> dict:
    with get_session() as session:
        milestone = session.get(Milestone, milestone_id)
        if not milestone:
            raise HTTPException(status_code=404, detail="Milestone not found.")
        accepted = session.exec(select(AcceptanceRecord).where(AcceptanceRecord.milestone_id == milestone_id, AcceptanceRecord.passed == True)).first()  # noqa: E712
        return {
            "milestone_id": milestone.milestone_id,
            "status": milestone.status,
            "accepted": bool(accepted),
        }
