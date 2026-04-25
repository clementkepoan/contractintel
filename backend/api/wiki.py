from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.db.database import get_session
from backend.wiki.generator import (
    build_wiki_manifest,
    read_wiki_page,
    resolve_contract_wiki_paths,
    resolve_milestone_wiki_path,
    run_wiki_lint,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


@router.get("")
def wiki_index() -> dict:
    return build_wiki_manifest()


@router.get("/lint")
def wiki_lint() -> dict:
    with get_session() as session:
        return run_wiki_lint(session)


@router.get("/contract/{contract_id}")
def wiki_contract(contract_id: str) -> dict:
    with get_session() as session:
        try:
            return resolve_contract_wiki_paths(session, contract_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Wiki contract page not found.") from exc


@router.get("/milestone/{milestone_id}")
def wiki_milestone(milestone_id: str) -> dict:
    with get_session() as session:
        try:
            return resolve_milestone_wiki_path(session, milestone_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Wiki milestone page not found.") from exc


@router.get("/page/{wiki_path:path}")
def wiki_page(wiki_path: str) -> dict:
    try:
        return read_wiki_page(wiki_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Wiki page not found.") from exc
