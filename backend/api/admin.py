from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend.db.database import get_session
from backend.pipeline.service import reprocess_documents

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ReprocessRequest(BaseModel):
    target: Literal["all", "file", "since_revision"]
    filename: str | None = None
    revision: str | None = None


@router.post("/reprocess")
def reprocess(payload: ReprocessRequest) -> dict:
    kwargs: dict[str, str] = {}
    if payload.target == "file":
        kwargs["filename"] = payload.filename or ""
    if payload.target == "since_revision":
        kwargs["revision"] = payload.revision or ""
    with get_session() as session:
        return reprocess_documents(session, target=payload.target, **kwargs)
