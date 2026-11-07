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


class UiBuckets:
    """The UI's chart buckets for a window - 24 x 1h, 28 x 6h or 30 x 1 day - aligned in the viewer's
    time zone, so counts made in the database line up with the charts' labels.

    ``local`` is the SQL expression for a timestamp column in that zone; ``hourly`` rows (local hour,
    ...) are folded into buckets with ``index``."""

    SPECS = {"24h": (1, 24), "7d": (6, 28), "30d": (24, 30)}  # hours per bucket, bucket count

    def __init__(self, span: str, tz: str):
        from datetime import timedelta
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from fastapi import HTTPException

        from app.db.base import utcnow

        if span not in self.SPECS:
            raise HTTPException(422, f"unknown range {span!r}")
        try:
            self.zone = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, f"unknown time zone {tz!r}") from None
        self.tz = tz
        hours, self.count = self.SPECS[span]
        self.step = timedelta(hours=hours)
        now = utcnow().astimezone(self.zone).replace(tzinfo=None)
        end = now.replace(minute=0, second=0, microsecond=0)
        end = end.replace(hour=0) if hours == 24 else end.replace(hour=end.hour // hours * hours)
        end += self.step
        self.starts = [end - (self.count - i) * self.step for i in range(self.count)]
        self.first = self.starts[0]
        # the window as aware datetimes, for filtering timestamp columns
        self.window = (self.first.replace(tzinfo=self.zone), end.replace(tzinfo=self.zone))

    def local(self, column):
        return func.timezone(self.tz, column)

    def hour(self, column):
        return func.date_trunc("hour", self.local(column))

    def index(self, local_hour: datetime) -> int | None:
        i = int((local_hour - self.first) / self.step)
        return i if 0 <= i < self.count else None

    def labels(self) -> list[str]:
        return [s.isoformat(timespec="minutes") for s in self.starts]
