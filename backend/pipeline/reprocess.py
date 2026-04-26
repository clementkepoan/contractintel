from __future__ import annotations

import argparse
import json

from backend.db.database import get_session
from backend.pipeline.service import reprocess_documents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reprocess extracted contract artifacts.")
    parser.add_argument("--all", action="store_true", help="Reprocess all active contracts.")
    parser.add_argument("--file", type=str, help="Reprocess a single active source file.")
    parser.add_argument("--since-revision", dest="since_revision", type=str, help="Reprocess active contracts not at the given pipeline revision.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.file:
        target = "file"
        kwargs = {"filename": args.file}
    elif args.since_revision:
        target = "since_revision"
        kwargs = {"revision": args.since_revision}
    else:
        target = "all"
        kwargs = {}
    with get_session() as session:
        result = reprocess_documents(session, target=target, **kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
