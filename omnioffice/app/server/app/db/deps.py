"""FastAPI 数据库依赖。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from .session import SessionLocal


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
