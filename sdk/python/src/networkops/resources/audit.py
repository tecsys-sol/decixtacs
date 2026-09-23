from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from networkops.models import AuditEvent, Page
from networkops.resources._base import Resource


class Audit(Resource):
    """Tamper-evident audit trail (per-tenant SHA-256 hash chain)."""

    def list(self, *, actor: str | None = None, action: str | None = None, target_type: str | None = None,
             target_id: str | None = None, start: datetime | None = None, end: datetime | None = None,
             limit: int = 100, offset: int = 0) -> Page[AuditEvent]:
        """``action`` is exact or a prefix ending in ``*`` (e.g. ``"tacacs.*"``)."""
        params = {"actor": actor, "action": action, "target_type": target_type, "target_id": target_id,
                  "start": start, "end": end}
        return self._c.get_page("/audit", AuditEvent, params, limit=limit, offset=offset)

    def iter(self, *, page_size: int = 500, max_items: int | None = None, **filters: Any) -> Iterator[AuditEvent]:
        return self._c.iterate("/audit", AuditEvent, filters, page_size=page_size, max_items=max_items)

    def verify(self) -> dict[str, Any]:
        """Recompute the hash chain: ``{"intact": bool, "events_verified": int}``."""
        result: dict[str, Any] = self._c.get("/audit/verify")
        return result
