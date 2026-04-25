from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama
from sqlmodel import select

from backend.config import settings
from backend.db.models import ChatMessage, ChatSession, Contract
from backend.pipeline.embeddings import embedding_model_ready
from backend.pipeline.indexer import hybrid_search_chunks
from backend.pipeline.llm import llm_available
from backend.pipeline.qdrant_store import qdrant_ready
from backend.wiki.generator import append_query_note, resolve_contract_wiki_paths


def ensure_chat_session(session: Any, chat_session_id: str | None, contract_id: str | None, first_query: str) -> ChatSession:
    if chat_session_id:
        existing = session.get(ChatSession, chat_session_id)
        if existing:
            return existing
    new_session = ChatSession(
        chat_session_id=chat_session_id or f"chat_{uuid4().hex[:12]}",
        title=first_query[:80],
        contract_id=contract_id,
    )
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    return new_session


def load_history(session: Any, chat_session_id: str, limit: int = 10) -> list[BaseMessage]:
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    ).all()
    messages: list[BaseMessage] = []
    for row in reversed(rows):
        if row.role == "human":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "ai":
            messages.append(AIMessage(content=row.content))
    return messages


def append_message(session: Any, chat_session_id: str, role: str, content: str) -> None:
    session.add(ChatMessage(chat_session_id=chat_session_id, role=role, content=content))
    chat_session = session.get(ChatSession, chat_session_id)
    if chat_session:
        from backend.db.models import now_utc

        chat_session.updated_at = now_utc()
        session.add(chat_session)
    session.commit()


def format_evidence(citations: list[dict[str, Any]]) -> str:
    lines = []
    for index, citation in enumerate(citations, start=1):
        lines.append(
            f"[{index}] {citation.get('text_snippet', '')} "
            f"(contract={citation.get('contract_id')}, paragraph={citation.get('para_start')}, page~{citation.get('page_estimate')})"
        )
    return "\n".join(lines)


def retrieval_mode() -> str:
    if embedding_model_ready() and qdrant_ready():
        return "hybrid_qdrant"
    if embedding_model_ready():
        return "hybrid_local"
    return "bm25_only"


def answer_with_langchain(
    *,
    session: Any,
    query: str,
    contract_ids: list[str],
    contract_id: str | None,
    top_k: int,
    chat_session_id: str | None,
    persist_to_wiki: bool = False,
) -> dict[str, Any]:
    chat_session = ensure_chat_session(session, chat_session_id, contract_id, query)
    citations = []
    for current_contract_id in contract_ids:
        contract = session.get(Contract, current_contract_id)
        for hit in hybrid_search_chunks(current_contract_id, query, top_k):
            hit["contract_id"] = current_contract_id
            hit["source_file"] = contract.source_file if contract else None
            try:
                hit.update(resolve_contract_wiki_paths(session, current_contract_id))
            except FileNotFoundError:
                pass
            citations.append(hit)
    citations = sorted(citations, key=lambda item: item["retrieval_score"], reverse=True)[:top_k]
    if not citations:
        answer = "No matching evidence found in the local indexes."
        append_message(session, chat_session.chat_session_id, "human", query)
        append_message(session, chat_session.chat_session_id, "ai", answer)
        return {
            "chat_session_id": chat_session.chat_session_id,
            "answer": answer,
            "citations": [],
            "answer_method": "no_evidence",
            "retrieval_mode": retrieval_mode(),
            "wiki_path": None,
        }

    evidence = format_evidence(citations)
    answer = None
    if llm_available():
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an offline contract analysis assistant. Answer only from the evidence. "
                    "Use prior chat only to resolve references, not as a source of new facts. "
                    "If the evidence does not contain the answer, say that the evidence is insufficient.",
                ),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "Question: {question}\n\nEvidence:\n{evidence}"),
            ]
        )
        chain = (
            prompt
            | ChatOllama(
                model=settings.local_model_name,
                base_url=settings.local_model_base_url,
                temperature=0,
                num_ctx=settings.local_model_num_ctx,
            )
            | StrOutputParser()
        )
        answer = chain.invoke({"question": query, "evidence": evidence, "chat_history": load_history(session, chat_session.chat_session_id)})

    if not answer:
        answer = f"Local evidence suggests: {' '.join(item['text_snippet'] for item in citations[:3])[:500]}"

    append_message(session, chat_session.chat_session_id, "human", query)
    append_message(session, chat_session.chat_session_id, "ai", answer)
    wiki_path = None
    if persist_to_wiki:
        wiki_path = append_query_note(
            session=session,
            chat_session_id=chat_session.chat_session_id,
            contract_id=contract_id,
            query=query,
            answer=answer,
            citations=citations,
            answer_method="langchain_ollama" if llm_available() else "langchain_extractive_fallback",
            retrieval_mode=retrieval_mode(),
        )
    return {
        "chat_session_id": chat_session.chat_session_id,
        "answer": answer,
        "citations": citations,
        "answer_method": "langchain_ollama" if llm_available() else "langchain_extractive_fallback",
        "retrieval_mode": retrieval_mode(),
        "wiki_path": wiki_path,
    }
