from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from backend.config import ensure_runtime_dirs, settings


ensure_runtime_dirs()
engine = create_engine(f"sqlite:///{settings.database_path}", echo=False, connect_args={"check_same_thread": False})


def _legacy_key(source_file: str) -> str:
    stem = Path(source_file or "contract").stem
    slug = "".join(char.lower() if char.isalnum() else "-" for char in stem)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "contract"


def _table_columns(table_name: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _table_columns(table_name):
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _migrate_sqlite_schema() -> None:
    if not settings.database_path.exists():
        return
    _add_column_if_missing("contract", "contract_key", "contract_key VARCHAR DEFAULT ''")
    _add_column_if_missing("contract", "version_number", "version_number INTEGER DEFAULT 1")
    _add_column_if_missing("contract", "superseded_by_contract_id", "superseded_by_contract_id VARCHAR")
    _add_column_if_missing("milestone", "milestone_key", "milestone_key VARCHAR DEFAULT ''")


def _backfill_legacy_identity() -> None:
    from backend.db.models import Contract, Milestone

    with Session(engine) as session:
        contracts = session.exec(select(Contract)).all()
        changed = False
        grouped: dict[str, list[Contract]] = {}
        for contract in contracts:
            if not contract.contract_key:
                contract.contract_key = _legacy_key(contract.source_file)
                changed = True
            grouped.setdefault(contract.contract_key, []).append(contract)
        for items in grouped.values():
            for index, contract in enumerate(sorted(items, key=lambda item: item.created_at), start=1):
                if not contract.version_number:
                    contract.version_number = index
                    contract.source_version = f"v{index}"
                    changed = True
        milestones = session.exec(select(Milestone)).all()
        for milestone in milestones:
            if not milestone.milestone_key:
                milestone.milestone_key = f"m{milestone.source_order:03d}"
                changed = True
        if changed:
            session.commit()


def init_db() -> None:
    from backend.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _migrate_sqlite_schema()
    _backfill_legacy_identity()


@contextmanager
def get_session() -> Session:
    init_db()
    with Session(engine) as session:
        yield session
