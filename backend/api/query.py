from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import ChatMessage, ChatSession, FiledQuery
from backend.config import settings
from backend.pipeline.langchain_query import answer_with_langchain, retrieve_query_evidence, stream_answer_with_langchain
from backend.pipeline.service import get_all_contracts

router = APIRouter(prefix="/api", tags=["query"])


def dedupe_filed_queries(rows: list[FiledQuery]) -> list[FiledQuery]:
    deduped: list[FiledQuery] = []
    seen: set[tuple[str, int | None, int | None, str, str]] = set()
    ordered = sorted(
        rows,
        key=lambda row: (
            row.chat_session_id,
            row.human_message_id is None,
            row.ai_message_id is None,
            row.created_at,
        ),
    )
    for row in ordered:
        key = (row.chat_session_id, row.human_message_id, row.ai_message_id, row.question, row.answer)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


class QueryPayload(BaseModel):
    query: str
    top_k: int = 10
    contract_id: str | None = None
    chat_session_id: str | None = None
    persist_to_wiki: bool = False
    persist_chat: bool = True


@router.post("/query")
def query_documents(payload: QueryPayload) -> dict:
    with get_session() as session:
        contract_ids = [payload.contract_id] if payload.contract_id else [item["contract_id"] for item in get_all_contracts(session)]
        return answer_with_langchain(
            session=session,
            query=payload.query,
            contract_ids=contract_ids,
            contract_id=payload.contract_id,
            top_k=payload.top_k,
            chat_session_id=payload.chat_session_id,
            persist_to_wiki=payload.persist_to_wiki,
            persist_chat=payload.persist_chat,
        )


@router.post("/query/stream")
def query_documents_stream(payload: QueryPayload) -> StreamingResponse:
    def event_stream():
        try:
            with get_session() as session:
                contract_ids = [payload.contract_id] if payload.contract_id else [item["contract_id"] for item in get_all_contracts(session)]
                for item in stream_answer_with_langchain(
                    session=session,
                    query=payload.query,
                    contract_ids=contract_ids,
                    contract_id=payload.contract_id,
                    top_k=payload.top_k,
                    chat_session_id=payload.chat_session_id,
                    persist_to_wiki=payload.persist_to_wiki,
                    persist_chat=payload.persist_chat,
                ):
                    yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"detail": str(exc)}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/query/retrieval")
def query_retrieval_only(payload: QueryPayload) -> dict:
    with get_session() as session:
        contract_ids = [payload.contract_id] if payload.contract_id else [item["contract_id"] for item in get_all_contracts(session)]
        if not contract_ids:
            raise HTTPException(status_code=404, detail="No ingested contracts available.")
        retrieval = retrieve_query_evidence(
            session=session,
            query=payload.query,
            contract_ids=contract_ids,
            top_k=payload.top_k,
        )
        return {
            "query": payload.query,
            "contract_id": payload.contract_id,
            "top_k": payload.top_k,
            "intents": retrieval["intents"],
            "expanded_query": retrieval["expanded_query"],
            "citations": retrieval["citations"],
            "retrieval_mode": retrieval["retrieval_mode"],
            "reranker_model_name": retrieval.get("reranker_model_name"),
            "retrieval_confident": retrieval.get("retrieval_confident"),
            "anchor_failure_reason": retrieval.get("anchor_failure_reason"),
            "answer_method": "retrieval_only",
            "model_name": None,
        }


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


@router.get("/chat/sessions/{chat_session_id}/latest-query")
def get_latest_query(chat_session_id: str) -> dict | None:
    with get_session() as session:
        rows = session.exec(
            select(FiledQuery).where(FiledQuery.chat_session_id == chat_session_id).order_by(FiledQuery.created_at.desc())
        ).all()
        deduped = dedupe_filed_queries(rows)
        if not deduped:
            return None
        row = deduped[-1]
        contract_scope = json.loads(row.contract_scope_json or "[]")
        return {
            "query_id": row.query_id,
            "chat_session_id": row.chat_session_id,
            "human_message_id": row.human_message_id,
            "ai_message_id": row.ai_message_id,
            "question": row.question,
            "answer": row.answer,
            "citations": json.loads(row.citations_json or "[]"),
            "wiki_path": row.wiki_path or None,
            "answer_method": row.answer_method,
            "retrieval_mode": row.retrieval_mode,
            "model_name": settings.local_query_model_name,
            "contract_id": contract_scope[0] if contract_scope else None,
            "created_at": row.created_at,
        }


@router.get("/chat/sessions/{chat_session_id}/turns")
def get_chat_turns(chat_session_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.exec(
            select(FiledQuery).where(FiledQuery.chat_session_id == chat_session_id).order_by(FiledQuery.created_at)
        ).all()
        rows = dedupe_filed_queries(rows)
        turns = []
        for row in rows:
            contract_scope = json.loads(row.contract_scope_json or "[]")
            turns.append(
                {
                    "query_id": row.query_id,
                    "chat_session_id": row.chat_session_id,
                    "human_message_id": row.human_message_id,
                    "ai_message_id": row.ai_message_id,
                    "question": row.question,
                    "answer": row.answer,
                    "citations": json.loads(row.citations_json or "[]"),
                    "wiki_path": row.wiki_path or None,
                    "answer_method": row.answer_method,
                    "retrieval_mode": row.retrieval_mode,
                    "model_name": settings.local_query_model_name,
                    "contract_id": contract_scope[0] if contract_scope else None,
                    "created_at": row.created_at,
                }
            )
        return turns
