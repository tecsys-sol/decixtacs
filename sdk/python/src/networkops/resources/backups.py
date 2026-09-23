from __future__ import annotations

import builtins
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from networkops.models import Backup, Diff, DriftEvent, Page, Restore, parse
from networkops.resources._base import Resource


class Backups(Resource):
    """Configuration backups (Git-backed), history, diffs, drift and restore."""

    def list(self, *, device_id: UUID | str | None = None, status: str | None = None, changed_only: bool = False,
             author: str | None = None, since: datetime | None = None, limit: int = 50,
             offset: int = 0) -> Page[Backup]:
        params = {"device_id": device_id, "status": status, "changed_only": changed_only or None,
                  "author": author, "since": since}
        return self._c.get_page("/backups", Backup, params, limit=limit, offset=offset)

    def iter(self, *, page_size: int = 200, max_items: int | None = None, **filters: Any) -> Iterator[Backup]:
        return self._c.iterate("/backups", Backup, filters, page_size=page_size, max_items=max_items)

    def run(self, device_ids: Sequence[UUID | str] = (), *, reason: str | None = None,
            change_request_id: UUID | str | None = None, run_async: bool = True) -> dict[str, Any]:
        """Trigger a backup. Async (default) returns ``{"task_id": ...}``; sync returns
        ``{"backups": [...]}``. An empty ``device_ids`` means every backup-enabled device."""
        out: dict[str, Any] = self._c.post("/backups/run", json={
            "device_ids": list(device_ids), "reason": reason, "change_request_id": change_request_id,
            "run_async": run_async})
        if "backups" in out:
            out["backups"] = [parse(Backup, b) for b in out["backups"]]
        return out

    def config(self, device_id: UUID | str, rev: str = "HEAD") -> str:
        """Stored (sanitised) configuration text at a Git revision (sha, ``HEAD~1`` ...)."""
        text: str = self._c.get(f"/devices/{device_id}/config", params={"rev": rev}, expect="text")
        return text

    def history(self, device_id: UUID | str, limit: int = 100) -> builtins.list[dict[str, Any]]:
        """Git commits touching the device's file: sha, author, email, timestamp, message."""
        result: builtins.list[dict[str, Any]] = self._c.get(f"/devices/{device_id}/history", params={"limit": limit})
        return result

    def diff(self, device_id: UUID | str, old: str, new: str = "HEAD", *, context: int = 3,
             include_inline: bool = False) -> Diff:
        return parse(Diff, self._c.get(f"/devices/{device_id}/diff", params={
            "old": old, "new": new, "context": context, "include_inline": include_inline}))

    def delete(self, backup_id: UUID | str) -> None:
        """Deletes the backup record; Git history is immutable and kept."""
        self._c.delete(f"/backups/{backup_id}")

    def restore(self, device_id: UUID | str, backup_id: UUID | str, *, dry_run: bool = True, confirm: bool = False,
                change_request_id: UUID | str | None = None) -> Restore:
        """Dry run (default) returns the device-side diff. A real push needs ``dry_run=False,
        confirm=True`` and - unless the tenant disabled it - an approved change covering the device."""
        return parse(Restore, self._c.post(f"/devices/{device_id}/restore", json={
            "backup_id": backup_id, "dry_run": dry_run, "confirm": confirm,
            "change_request_id": change_request_id}))

    def drift(self, *, resolved: bool = False, device_id: UUID | str | None = None, limit: int = 50,
              offset: int = 0) -> Page[DriftEvent]:
        return self._c.get_page("/drift", DriftEvent, {"resolved": resolved, "device_id": device_id},
                                limit=limit, offset=offset)

    def drift_check(self, device_id: UUID | str) -> dict[str, Any]:
        """Collect the running config now and compare it to the last backup: ``{drifted, diff}``."""
        result: dict[str, Any] = self._c.post(f"/devices/{device_id}/drift-check")
        return result

    def search(self, *, kind: str | None = None, key: str | None = None, peer_as: int | None = None,
               community: str | None = None, text: str | None = None,
               limit: int = 200) -> builtins.list[dict[str, Any]]:
        """Config intelligence search, e.g. ``search(peer_as=13335)`` or ``search(community="65000:100")``."""
        result: builtins.list[dict[str, Any]] = self._c.get("/config-search", params={
            "kind": kind, "key": key, "peer_as": peer_as, "community": community, "text": text, "limit": limit})
        return result

    def analyse_diff(self, diff: str) -> dict[str, Any]:
        """Change risk analysis of a unified diff: ``{score, level, findings, summary}``."""
        result: dict[str, Any] = self._c.post("/analyse-diff", json={"diff": diff})
        return result
