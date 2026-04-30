from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from datetime import UTC, datetime


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WIKI_DIR = ROOT / "wiki"
RESET_MARKER = DATA_DIR / "reset_marker.txt"


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def empty_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        remove_path(child)


def reset_state() -> None:
    empty_directory(DATA_DIR / "uploads")
    empty_directory(DATA_DIR / "extracted")
    empty_directory(DATA_DIR / "indexes")
    empty_directory(WIKI_DIR / "contracts")
    empty_directory(WIKI_DIR / "contract_versions")
    empty_directory(WIKI_DIR / "milestones")
    empty_directory(WIKI_DIR / "milestone_versions")
    empty_directory(WIKI_DIR / "sources")
    empty_directory(WIKI_DIR / "queries")
    remove_path(DATA_DIR / "db.sqlite")
    remove_path(WIKI_DIR / "index.md")
    remove_path(WIKI_DIR / "log.md")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESET_MARKER.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset local demo state for a fresh ingestion run.")
    parser.add_argument(
        "--docker-volumes",
        action="store_true",
        help="Also remove Docker named volumes for Qdrant and HuggingFace cache by printing the compose command to run.",
    )
    args = parser.parse_args()
    reset_state()
    print("Reset local data/wiki state.")
    print("Next step: rerun ingestion from scratch.")
    if args.docker_volumes:
        print("To reset Docker volumes as well, run: docker compose down -v")


if __name__ == "__main__":
    main()
