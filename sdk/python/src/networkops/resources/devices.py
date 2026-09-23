from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from networkops.models import Device, Page, parse
from networkops.resources._base import Resource


class Devices(Resource):
    """Inventory devices (``/devices``). Results honour your RBAC/ABAC scope."""

    def list(self, *, q: str | None = None, site_id: UUID | str | None = None, platform: str | None = None,
             vendor: str | None = None, role: str | None = None, status: str | None = None,
             group_id: UUID | str | None = None, backup_status: str | None = None, limit: int = 50,
             offset: int = 0) -> Page[Device]:
        return self._c.get_page("/devices", Device, _filters(locals()), limit=limit, offset=offset)

    def iter(self, *, page_size: int = 200, max_items: int | None = None, **filters: Any) -> Iterator[Device]:
        return self._c.iterate("/devices", Device, filters, page_size=page_size, max_items=max_items)

    def get(self, device_id: UUID | str) -> Device:
        return parse(Device, self._c.get(f"/devices/{device_id}"))

    def create(self, *, hostname: str, management_ip: str, **fields: Any) -> Device:
        """Fields: site_id, rack_id, platform_id, vendor_id, credential_id, serial, os_version, role,
        status, backup_enabled, ssh_port, tags, group_ids."""
        return parse(Device, self._c.post("/devices", json={"hostname": hostname, "management_ip": management_ip,
                                                             **fields}))

    def update(self, device_id: UUID | str, **fields: Any) -> Device:
        return parse(Device, self._c.patch(f"/devices/{device_id}", json=fields))

    def delete(self, device_id: UUID | str) -> None:
        self._c.delete(f"/devices/{device_id}")

    def find(self, hostname: str) -> Device | None:
        """Exact hostname lookup (the list endpoint does substring search)."""
        for d in self.iter(q=hostname, page_size=50):
            if d.hostname == hostname:
                return d
        return None


def _filters(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k not in ("self", "limit", "offset") and v is not None}
