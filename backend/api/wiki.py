from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.wiki.generator import list_wiki_pages, read_wiki_page

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


@router.get("")
def wiki_index() -> dict:
    return {"pages": list_wiki_pages()}


@router.get("/{wiki_path:path}")
def wiki_page(wiki_path: str) -> dict:
    try:
        content = read_wiki_page(wiki_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Wiki page not found.") from exc
    return {"path": wiki_path, "content": content}

