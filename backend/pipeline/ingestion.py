from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from fastapi import UploadFile

from backend.config import settings


def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def persist_upload(upload: UploadFile) -> Path:
    target = settings.uploads_dir / upload.filename
    source_name = getattr(upload.file, "name", None)
    if source_name and Path(source_name).resolve() == target.resolve():
        upload.file.seek(0)
        return target
    with target.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)
    upload.file.seek(0)
    return target


def convert_doc_to_docx(path: Path) -> Path:
    if path.suffix.lower() != ".doc":
        return path
    if shutil.which("soffice") is None:
        raise RuntimeError("LibreOffice soffice is required for .doc conversion but is not installed.")
    with tempfile.TemporaryDirectory() as temp_dir:
        command = [
            "soffice",
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            temp_dir,
            str(path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {completed.stderr.strip()}")
        converted = Path(temp_dir) / f"{path.stem}.docx"
        if not converted.exists():
            raise RuntimeError("LibreOffice conversion did not produce a .docx file.")
        final_path = settings.uploads_dir / converted.name
        shutil.copy2(converted, final_path)
        return final_path


def classify_document(paragraphs: list[str]) -> str:
    joined = "\n".join(paragraphs)
    if "契約" in joined or "承攬" in joined:
        return "contract"
    if ("專案名稱" in joined or "需求" in joined or "功能" in joined) and "總價" not in joined and "付款辦法" not in joined:
        return "rfp"
    if "招標" in joined or "規範" in joined:
        return "rfp"
    if "施工說明" in joined or "施工規範" in joined:
        return "construction_instruction"
    return "contract"


def load_document(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    working_path = convert_doc_to_docx(path) if path.suffix.lower() == ".doc" else path
    document = Document(str(working_path))
    paragraphs: list[dict[str, Any]] = []
    for index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        paragraphs.append(
            {
                "paragraph_index": index,
                "page_estimate": (index // 15) + 1,
                "block_id": f"{working_path.stem}_block_{index:04d}",
                "text": text,
            }
        )
    return {
        "source_file": path.name,
        "working_file": working_path.name,
        "paragraphs": paragraphs,
        "doc_category": classify_document([item["text"] for item in paragraphs]),
    }
