from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import ChatMessage, ChatSession
from backend.pipeline.langchain_query import answer_with_langchain
from backend.pipeline.service import get_all_contracts

router = APIRouter(prefix="/api", tags=["query"])


class QueryPayload(BaseModel):
    query: str
    top_k: int = 5
    contract_id: str | None = None
    chat_session_id: str | None = None


@router.post("/query")
def query_documents(payload: QueryPayload) -> dict:
    with get_session() as session:
        contract_ids = [payload.contract_id] if payload.contract_id else [item["contract_id"] for item in get_all_contracts(session)]
        if not contract_ids:
            raise HTTPException(status_code=404, detail="No ingested contracts available.")
        return answer_with_langchain(
            session=session,
            query=payload.query,
            contract_ids=contract_ids,
            contract_id=payload.contract_id,
            top_k=payload.top_k,
            chat_session_id=payload.chat_session_id,
        )


@router.get("/chat/sessions")
def list_chat_sessions() -> list[dict]:
    with get_session() as session:
        rows = session.exec(select(ChatSession).order_by(ChatSession.updated_at.desc())).all()
        return [
            {
                "chat_session_id": row.chat_session_id,
                "title": row.title,
                "contract_id": row.contract_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]


@router.get("/chat/sessions/{chat_session_id}/messages")
def get_chat_messages(chat_session_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.exec(
            select(ChatMessage).where(ChatMessage.chat_session_id == chat_session_id).order_by(ChatMessage.created_at)
        ).all()
        return [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at,
            }
            for row in rows
        ]
