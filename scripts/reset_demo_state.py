from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WIKI_DIR = ROOT / "wiki"


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
    empty_directory(WIKI_DIR / "milestones")
    remove_path(DATA_DIR / "db.sqlite")
    remove_path(WIKI_DIR / "index.md")
    remove_path(WIKI_DIR / "log.md")


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
