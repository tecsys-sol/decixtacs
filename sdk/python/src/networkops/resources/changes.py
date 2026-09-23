from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from networkops.models import ChangeRequest, Page, parse
from networkops.resources._base import Resource


class Changes(Resource):
    """Change requests: draft -> pending_approval -> approved -> implemented -> closed
    (reject / cancel). Approval takes pre-change backups, implement takes post-change backups."""

    def list(self, *, state: str | None = None, q: str | None = None, limit: int = 50,
             offset: int = 0) -> Page[ChangeRequest]:
        return self._c.get_page("/changes", ChangeRequest, {"state": state, "q": q}, limit=limit, offset=offset)

    def iter(self, *, page_size: int = 100, max_items: int | None = None, **filters: Any) -> Iterator[ChangeRequest]:
        return self._c.iterate("/changes", ChangeRequest, filters, page_size=page_size, max_items=max_items)

    def get(self, change_id: UUID | str) -> dict[str, Any]:
        """``{"change": ChangeRequest, "comments", "backups", "allowed_transitions"}``."""
        data: dict[str, Any] = self._c.get(f"/changes/{change_id}")
        data["change"] = parse(ChangeRequest, data["change"])
        return data

    def create(self, *, title: str, device_ids: Sequence[UUID | str] = (), risk: str = "medium",
               description: str | None = None, scheduled_start: datetime | None = None,
               scheduled_end: datetime | None = None, implementation_plan: str | None = None,
               rollback_plan: str | None = None, external_ticket: str | None = None) -> ChangeRequest:
        body = {"title": title, "device_ids": list(device_ids), "risk": risk, "description": description,
                "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
                "implementation_plan": implementation_plan, "rollback_plan": rollback_plan,
                "external_ticket": external_ticket}
        return parse(ChangeRequest, self._c.post("/changes", json=body))

    def update(self, change_id: UUID | str, **fields: Any) -> ChangeRequest:
        """Only draft/rejected changes can be edited (PATCH with the full ChangeIn body)."""
        return parse(ChangeRequest, self._c.patch(f"/changes/{change_id}", json=fields))

    def transition(self, change_id: UUID | str, transition: str, *, comment: str | None = None,
                   take_backup: bool = True) -> ChangeRequest:
        return parse(ChangeRequest, self._c.post(f"/changes/{change_id}/transition", json={
            "transition": transition, "comment": comment, "take_backup": take_backup}))

    def submit(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        return self.transition(change_id, "submit", comment=comment)

    def approve(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        """Four-eyes: the requester cannot approve their own change."""
        return self.transition(change_id, "approve", comment=comment)

    def reject(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        return self.transition(change_id, "reject", comment=comment)

    def implement(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        return self.transition(change_id, "implement", comment=comment)

    def close(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        return self.transition(change_id, "close", comment=comment)

    def cancel(self, change_id: UUID | str, comment: str | None = None) -> ChangeRequest:
        return self.transition(change_id, "cancel", comment=comment)

    def comment(self, change_id: UUID | str, body: str) -> str:
        cid: str = self._c.post(f"/changes/{change_id}/comments", json={"body": body})["id"]
        return cid
