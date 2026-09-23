"""Upload asciicast v2 session recordings from a spool directory to ``POST /api/v1/sessions``.

The SSH bastion / recorder drops ``<name>.cast`` files into the spool directory. Metadata comes
from an optional sidecar ``<name>.json``::

    {"username": "alice", "device_address": "192.0.2.1", "source_address": "198.51.100.7",
     "started_at": "2026-09-23T10:00:00Z"}

or, without sidecar, from the file name ``<username>@<device_address>[@<source_address>]@<anything>.cast``.
A file is picked up once it has not been modified for ``settle_seconds`` (recording finished).
Uploaded files are deleted (or moved to ``sent/`` with ``keep=True``); files the platform rejects
as invalid are moved to ``failed/`` with a ``.error`` note; transient errors are retried later.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from nom_tacacs_agent.api import AgentAPI, ApiError
from nom_tacacs_agent.backoff import Backoff

log = logging.getLogger(__name__)


def recording_metadata(cast: Path) -> dict[str, str] | None:
    sidecar = cast.with_suffix(".json")
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            return None
        if meta.get("username") and meta.get("device_address"):
            return {k: str(meta[k]) for k in ("username", "device_address", "source_address", "started_at")
                    if meta.get(k)}
        return None
    parts = cast.stem.split("@")
    if len(parts) >= 3:
        meta = {"username": parts[0], "device_address": parts[1]}
        if len(parts) >= 4:
            meta["source_address"] = parts[2]
        return meta
    return None


class RecordingUploader:
    def __init__(self, api: AgentAPI, spool_dir: Path, *, settle_seconds: float = 10.0, keep: bool = False,
                 interval: float = 15.0, clock: Callable[[], float] = time.time,
                 stop: threading.Event | None = None, backoff: Backoff | None = None):
        self.api = api
        self.spool = Path(spool_dir)
        self.settle = settle_seconds
        self.keep = keep
        self.interval = interval
        self.clock = clock
        self.stop = stop or threading.Event()
        self.backoff = backoff or Backoff(base=5, maximum=600)

    def _move(self, cast: Path, sub: str, note: str | None = None) -> None:
        dest = self.spool / sub
        dest.mkdir(parents=True, exist_ok=True)
        for f in (cast, cast.with_suffix(".json")):
            if f.exists():
                shutil.move(str(f), dest / f.name)
        if note:
            (dest / f"{cast.stem}.error").write_text(note + "\n", encoding="utf-8")

    def scan_once(self) -> tuple[int, int]:
        """Returns (uploaded, rejected). Raises ApiError on transient failures."""
        uploaded = rejected = 0
        if not self.spool.is_dir():
            return 0, 0
        now = self.clock()
        for cast in sorted(self.spool.glob("*.cast")):
            try:
                if now - cast.stat().st_mtime < self.settle:
                    continue
            except FileNotFoundError:
                continue
            meta = recording_metadata(cast)
            if meta is None:
                self._move(cast, "failed", "missing metadata: add a .json sidecar or use user@device@...cast naming")
                rejected += 1
                continue
            try:
                self.api.upload_recording(cast, meta)
            except ApiError as exc:
                if exc.permanent:
                    self._move(cast, "failed", str(exc))
                    rejected += 1
                    continue
                raise
            if self.keep:
                self._move(cast, "sent")
            else:
                cast.unlink(missing_ok=True)
                cast.with_suffix(".json").unlink(missing_ok=True)
            uploaded += 1
            log.info("uploaded session recording %s (%s@%s)", cast.name, meta["username"], meta["device_address"])
        return uploaded, rejected

    def run(self) -> None:
        log.info("recording uploader watching %s", self.spool)
        while not self.stop.is_set():
            try:
                self.scan_once()
                self.backoff.reset()
                wait = self.interval
            except ApiError as exc:
                wait = self.backoff.next_delay()
                log.warning("recording upload failed (%s); retrying in %.0fs", exc, wait)
            except Exception:  # noqa: BLE001
                log.exception("recording uploader iteration failed")
                wait = self.interval
            self.stop.wait(wait)
