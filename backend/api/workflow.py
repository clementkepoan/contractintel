from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import AcceptanceRecord, Milestone, Payment, PaymentRequest

router = APIRouter(prefix="/api", tags=["workflow"])


class AcceptancePayload(BaseModel):
    milestone_id: str
    passed: bool
    inspector_name: str | None = None
    notes: str | None = None


class PaymentRequestPayload(BaseModel):
    milestone_id: str
    requested_amount: int
    remarks: str | None = None


class PaymentPayload(BaseModel):
    payment_request_id: int
    paid_amount: int
    remarks: str | None = None


@router.post("/acceptance")
def create_acceptance(payload: AcceptancePayload) -> dict:
    with get_session() as session:
        milestone = session.get(Milestone, payload.milestone_id)
        if not milestone:
            raise HTTPException(status_code=404, detail="Milestone not found.")
        acceptance = AcceptanceRecord(
            milestone_id=payload.milestone_id,
            passed=payload.passed,
            inspector_name=payload.inspector_name,
            notes=payload.notes,
        )
        session.add(acceptance)
        milestone.status = "accepted" if payload.passed else "pending_acceptance"
        session.add(milestone)
        session.commit()
        return {"status": milestone.status, "accepted_at": acceptance.accepted_at}


@router.get("/acceptance/{milestone_id}")
def acceptance_history(milestone_id: str) -> list[dict]:
    with get_session() as session:
        records = session.exec(select(AcceptanceRecord).where(AcceptanceRecord.milestone_id == milestone_id)).all()
        return [
            {
                "id": record.id,
                "passed": record.passed,
                "accepted_at": record.accepted_at,
                "inspector_name": record.inspector_name,
                "notes": record.notes,
            }
            for record in records
        ]


@router.get("/workflow/{milestone_id}")
def milestone_workflow_history(milestone_id: str) -> dict:
    with get_session() as session:
        milestone = session.get(Milestone, milestone_id)
        if not milestone:
            raise HTTPException(status_code=404, detail="Milestone not found.")
        acceptance_records = session.exec(select(AcceptanceRecord).where(AcceptanceRecord.milestone_id == milestone_id)).all()
        payment_requests = session.exec(select(PaymentRequest).where(PaymentRequest.milestone_id == milestone_id)).all()
        payments = session.exec(select(Payment).where(Payment.milestone_id == milestone_id)).all()
        return {
            "milestone_id": milestone_id,
            "status": milestone.status,
            "acceptance_records": [
                {
                    "id": record.id,
                    "passed": record.passed,
                    "accepted_at": record.accepted_at,
                    "inspector_name": record.inspector_name,
                    "notes": record.notes,
                }
                for record in acceptance_records
            ],
            "payment_requests": [
                {
                    "id": request.id,
                    "milestone_id": request.milestone_id,
                    "requested_amount": request.requested_amount,
                    "requested_at": request.requested_at,
                    "remarks": request.remarks,
                }
                for request in payment_requests
            ],
            "payments": [
                {
                    "id": payment.id,
                    "payment_request_id": payment.payment_request_id,
                    "milestone_id": payment.milestone_id,
                    "paid_amount": payment.paid_amount,
                    "paid_at": payment.paid_at,
                    "remarks": payment.remarks,
                }
                for payment in payments
            ],
        }


@router.post("/payment-request")
def create_payment_request(payload: PaymentRequestPayload) -> dict:
    with get_session() as session:
        milestone = session.get(Milestone, payload.milestone_id)
        if not milestone:
            raise HTTPException(status_code=404, detail="Milestone not found.")
        accepted = session.exec(select(AcceptanceRecord).where(AcceptanceRecord.milestone_id == payload.milestone_id, AcceptanceRecord.passed == True)).first()  # noqa: E712
        if not accepted:
            raise HTTPException(status_code=400, detail="Payment request requires a passed acceptance record.")
        payment_request = PaymentRequest(
            milestone_id=payload.milestone_id,
            requested_amount=payload.requested_amount,
            remarks=payload.remarks,
        )
        milestone.status = "payment_requested"
        session.add(payment_request)
        session.add(milestone)
        session.commit()
        session.refresh(payment_request)
        return {
            "id": payment_request.id,
            "milestone_id": payment_request.milestone_id,
            "requested_amount": payment_request.requested_amount,
            "requested_at": payment_request.requested_at,
            "status": milestone.status,
        }


@router.get("/payment-request/{payment_request_id}")
def get_payment_request(payment_request_id: int) -> dict:
    with get_session() as session:
        payment_request = session.get(PaymentRequest, payment_request_id)
        if not payment_request:
            raise HTTPException(status_code=404, detail="Payment request not found.")
        return {
            "id": payment_request.id,
            "milestone_id": payment_request.milestone_id,
            "requested_amount": payment_request.requested_amount,
            "requested_at": payment_request.requested_at,
            "remarks": payment_request.remarks,
        }


@router.post("/payment")
def log_payment(payload: PaymentPayload) -> dict:
    with get_session() as session:
        payment_request = session.get(PaymentRequest, payload.payment_request_id)
        if not payment_request:
            raise HTTPException(status_code=404, detail="Payment request not found.")
        milestone = session.get(Milestone, payment_request.milestone_id)
        payment = Payment(
            payment_request_id=payment_request.id,
            milestone_id=payment_request.milestone_id,
            paid_amount=payload.paid_amount,
            remarks=payload.remarks,
            paid_at=datetime.now(UTC),
        )
        if milestone:
            milestone.status = "paid"
            session.add(milestone)
        session.add(payment)
        session.commit()
        session.refresh(payment)
        return {
            "id": payment.id,
            "milestone_id": payment.milestone_id,
            "paid_amount": payment.paid_amount,
            "paid_at": payment.paid_at,
        }
