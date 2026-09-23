"""Shared schema helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def paginate(db: Session, stmt, schema, limit: int, offset: int) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return {"items": [schema.model_validate(r) for r in rows], "total": total or 0, "limit": limit, "offset": offset}


class IdName(ORM):
    id: uuid.UUID
    name: str


class Message(BaseModel):
    detail: str


__all__ = ["ORM", "Page", "paginate", "IdName", "Message", "datetime", "uuid"]
