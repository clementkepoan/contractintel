from __future__ import annotations

from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from backend.config import ensure_runtime_dirs, settings


ensure_runtime_dirs()
engine = create_engine(f"sqlite:///{settings.database_path}", echo=False, connect_args={"check_same_thread": False})


def init_db() -> None:
    from backend.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Session:
    init_db()
    with Session(engine) as session:
        yield session
