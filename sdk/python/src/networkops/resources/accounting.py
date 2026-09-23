from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from networkops.models import CommandRecord, Page
from networkops.resources._base import Resource


class Accounting(Resource):
    """TACACS+ command accounting search."""

    def search(self, *, user: str | None = None, device: str | None = None, command: str | None = None,
               result: str | None = None, start: datetime | None = None, end: datetime | None = None,
               limit: int = 100, offset: int = 0) -> Page[CommandRecord]:
        """``command`` is a substring; prefix it with ``~`` for a (PostgreSQL) regex.
        ``device`` matches hostname or management address. ``result``: accounted|denied."""
        params = {"user": user, "device": device, "command": command, "result": result, "start": start, "end": end}
        return self._c.get_page("/accounting/commands", CommandRecord, params, limit=limit, offset=offset)

    def iter(self, *, page_size: int = 500, max_items: int | None = None, **filters: Any) -> Iterator[CommandRecord]:
        return self._c.iterate("/accounting/commands", CommandRecord, filters, page_size=page_size,
                               max_items=max_items)

    def top(self, days: int = 7) -> dict[str, Any]:
        """Top users and devices by command count: ``{"users": [...], "devices": [...]}``."""
        result: dict[str, Any] = self._c.get("/accounting/top", params={"days": days})
        return result
