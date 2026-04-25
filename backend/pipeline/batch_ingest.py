from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from backend.config import settings
from backend.db.database import get_session, init_db
from backend.pipeline.service import ingest_upload


class LocalUploadFile(UploadFile):
    def __init__(self, path: Path) -> None:
        super().__init__(filename=path.name, file=path.open("rb"))


def main() -> None:
    init_db()
    uploads = sorted(settings.uploads_dir.glob("*"))
    with get_session() as session:
        for path in uploads:
            if path.suffix.lower() not in {".doc", ".docx"}:
                continue
            result = ingest_upload(session, LocalUploadFile(path))
            print(f"Ingested {result['contract_name']} ({result['contract_id']})")


if __name__ == "__main__":
    main()

