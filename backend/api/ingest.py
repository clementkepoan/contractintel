from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from sqlmodel import select

from backend.db.database import get_session
from backend.db.models import IngestRun, IngestRunItem
from backend.pipeline.batch_ingest import LocalUploadFile
from backend.pipeline.ingestion import persist_upload
from backend.pipeline.service import ingest_upload

router = APIRouter(prefix="/api", tags=["ingest"])

TERMINAL_RUN_STATUSES = {"completed", "failed", "completed_with_errors"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _serialize_run(session, run: IngestRun) -> dict:
    items = session.exec(
        select(IngestRunItem).where(IngestRunItem.run_id == run.run_id).order_by(IngestRunItem.upload_order)
    ).all()
    completed_count = sum(1 for item in items if item.status == "completed")
    failed_count = sum(1 for item in items if item.status == "failed")
    processing_item = next((item for item in items if item.status == "processing"), None)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "total_files": run.total_files,
        "completed_files": completed_count,
        "failed_files": failed_count,
        "processing_file": processing_item.source_file if processing_item else None,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
        "items": [
            {
                "item_id": item.item_id,
                "source_file": item.source_file,
                "upload_order": item.upload_order,
                "status": item.status,
                "contract_id": item.contract_id,
                "contract_name": item.contract_name,
                "error_message": item.error_message,
                "ingest_action": item.ingest_action,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "finished_at": item.finished_at,
            }
            for item in items
        ],
    }


def _latest_active_run(session) -> IngestRun | None:
    rows = session.exec(select(IngestRun).order_by(IngestRun.created_at.desc())).all()
    for row in rows:
        if row.status not in TERMINAL_RUN_STATUSES:
            return row
    return None


def _finalize_run(session, run: IngestRun) -> None:
    items = session.exec(select(IngestRunItem).where(IngestRunItem.run_id == run.run_id)).all()
    if items and all(item.status == "completed" for item in items):
        run.status = "completed"
    elif items and any(item.status == "failed" for item in items):
        run.status = "completed_with_errors" if any(item.status == "completed" for item in items) else "failed"
    else:
        run.status = "running"
        run.updated_at = now_utc()
        session.add(run)
        session.commit()
        return
    run.updated_at = now_utc()
    run.finished_at = now_utc()
    session.add(run)
    session.commit()


def _process_ingest_run(run_id: str) -> None:
    with get_session() as session:
        run = session.get(IngestRun, run_id)
        if not run or run.status in TERMINAL_RUN_STATUSES:
            return
        run.status = "running"
        run.updated_at = now_utc()
        session.add(run)
        session.commit()

    with get_session() as session:
        items = session.exec(
            select(IngestRunItem).where(IngestRunItem.run_id == run_id).order_by(IngestRunItem.upload_order)
        ).all()
        for item in items:
            row = session.get(IngestRunItem, item.item_id)
            run = session.get(IngestRun, run_id)
            if not row or not run:
                continue
            row.status = "processing"
            row.updated_at = now_utc()
            run.status = "running"
            run.updated_at = now_utc()
            session.add(row)
            session.add(run)
            session.commit()
            try:
                result = ingest_upload(session, LocalUploadFile(Path(row.stored_path)))
                row.status = "completed"
                row.contract_id = result.get("contract_id")
                row.contract_name = result.get("contract_name")
                row.ingest_action = result.get("ingest_action")
                row.error_message = None
            except Exception as exc:  # pragma: no cover - operational path
                row.status = "failed"
                row.error_message = str(exc)
            row.updated_at = now_utc()
            row.finished_at = now_utc()
            session.add(row)
            session.commit()
        run = session.get(IngestRun, run_id)
        if run:
            _finalize_run(session, run)


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


@router.post("/ingest/runs")
def create_ingest_run(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)) -> dict:
    uploads = [upload for upload in files if upload.filename]
    if not uploads:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    with get_session() as session:
        active_run = _latest_active_run(session)
        if active_run:
            raise HTTPException(status_code=409, detail="A document processing run is already active.")
        run = IngestRun(run_id=f"ingest_run_{uuid4().hex[:12]}", status="queued", total_files=len(uploads))
        session.add(run)
        session.flush()
        for index, upload in enumerate(uploads, start=1):
            stored_path = persist_upload(upload)
            session.add(
                IngestRunItem(
                    item_id=f"ingest_item_{uuid4().hex[:12]}",
                    run_id=run.run_id,
                    source_file=upload.filename or stored_path.name,
                    upload_order=index,
                    stored_path=str(stored_path),
                    status="queued",
                )
            )
        session.commit()
        session.refresh(run)
        payload = _serialize_run(session, run)
    background_tasks.add_task(_process_ingest_run, run.run_id)
    return payload


@router.get("/ingest/runs/active")
def active_ingest_run() -> dict | None:
    with get_session() as session:
        run = _latest_active_run(session)
        if not run:
            return None
        return _serialize_run(session, run)


@router.get("/ingest/runs/{run_id}")
def get_ingest_run(run_id: str) -> dict:
    with get_session() as session:
        run = session.get(IngestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Ingest run not found.")
        return _serialize_run(session, run)
