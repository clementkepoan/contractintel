from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from backend.db.database import get_session
from backend.pipeline.service import ingest_upload

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest")
def ingest_document(file: UploadFile = File(...)) -> dict:
    with get_session() as session:
        return ingest_upload(session, file)


@router.post("/ingest/batch")
def ingest_documents(files: list[UploadFile] = File(...)) -> dict:
    results = []
    with get_session() as session:
        for upload in files:
            results.append(ingest_upload(session, upload))
    return {"items": results}

