from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def now_utc() -> datetime:
    return datetime.now(UTC)


class Contract(SQLModel, table=True):
    contract_id: str = Field(primary_key=True, index=True)
    contract_name: str
    source_file: str = Field(index=True)
    source_version: str = Field(default="v1")
    doc_category: str = Field(default="contract")
    contract_type: str = Field(default="lump_sum")
    currency: str = Field(default="TWD")
    total_amount: Optional[int] = Field(default=None)
    total_amount_is_tax_included: bool = Field(default=False)
    extraction_method: str = Field(default="regex")
    status: str = Field(default="draft")
    validation_status: str = Field(default="pending")
    raw_json_path: str
    source_hash: str = Field(index=True)
    supersedes_contract_id: Optional[str] = Field(default=None, index=True)
    is_superseded: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Milestone(SQLModel, table=True):
    milestone_id: str = Field(primary_key=True, index=True)
    contract_id: str = Field(index=True)
    name: str
    source_order: int = Field(index=True)
    amount: Optional[int] = Field(default=None)
    percentage: Optional[float] = Field(default=None)
    work_items_json: str = Field(default="[]")
    acceptance_criteria: Optional[str] = Field(default=None)
    payment_condition: Optional[str] = Field(default=None)
    status: str = Field(default="pending_acceptance")
    citations_json: str = Field(default="[]")


class Citation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contract_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    field_name: str = Field(index=True)
    source_file: str
    para_start: int
    para_end: int
    page_estimate: int
    char_offset_start: int = Field(default=0)
    char_offset_end: int = Field(default=0)
    text_snippet: str
    block_id: str = Field(index=True)
    extraction_method: str = Field(default="regex")
    regex_pattern: Optional[str] = Field(default=None)


class ValidationWarning(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contract_id: str = Field(index=True)
    code: str = Field(index=True)
    severity: str
    message: str
    citations_json: str = Field(default="[]")


class AcceptanceRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    milestone_id: str = Field(index=True)
    passed: bool = Field(default=False)
    accepted_at: datetime = Field(default_factory=now_utc)
    inspector_name: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)


class PaymentRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    milestone_id: str = Field(index=True)
    requested_amount: int
    requested_at: datetime = Field(default_factory=now_utc)
    remarks: Optional[str] = Field(default=None)


class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    payment_request_id: int = Field(index=True)
    milestone_id: str = Field(index=True)
    paid_amount: int
    paid_at: datetime = Field(default_factory=now_utc)
    remarks: Optional[str] = Field(default=None)


class ChatSession(SQLModel, table=True):
    chat_session_id: str = Field(primary_key=True, index=True)
    title: Optional[str] = Field(default=None)
    contract_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_session_id: str = Field(index=True)
    role: str = Field(index=True)
    content: str
    created_at: datetime = Field(default_factory=now_utc)
