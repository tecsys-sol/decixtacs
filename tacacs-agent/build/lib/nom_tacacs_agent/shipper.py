"""Batch tailed log lines to ``POST /api/v1/accounting/ingest`` with retry/backoff.

* A batch is retried (exponential backoff with jitter, capped) until the platform accepts it;
  offsets are committed only afterwards (at-least-once delivery).
* ``413``/``422``/``400`` mean the batch itself is unacceptable: it is split in halves until the
  offending line is isolated, which is then dropped and counted, so one bad line can never wedge
  the pipeline.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field

from nom_tacacs_agent.api import AgentAPI, ApiError
from nom_tacacs_agent.backoff import Backoff
from nom_tacacs_agent.tailer import FileTailer

log = logging.getLogger(__name__)


class Stopped(Exception):
    """Raised when shutdown is requested while a batch is still being retried."""


@dataclass
class ShipperStats:
    batches: int = 0
    lines: int = 0
    dropped: int = 0
    retries: int = 0
    accepted: dict[str, int] = field(default_factory=dict)


class LogShipper:
    def __init__(self, api: AgentAPI, tailers: Sequence[FileTailer], *, batch_size: int = 500,
                 flush_interval: float = 2.0, backoff: Backoff | None = None,
                 stop: threading.Event | None = None):
        self.api = api
        self.tailers = list(tailers)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.backoff = backoff or Backoff()
        self.stop = stop or threading.Event()
        self.stats = ShipperStats()

    def _post(self, lines: list[str]) -> None:
        while True:
            try:
                result = self.api.ingest(lines)
            except ApiError as exc:
                if exc.permanent:
                    self._split(lines, exc)
                    return
                self.stats.retries += 1
                delay = self.backoff.next_delay()
                level = logging.ERROR if exc.status_code in (401, 403) else logging.WARNING
                log.log(level, "ingest of %d lines failed (%s); retrying in %.1fs", len(lines), exc, delay)
                if self.stop.wait(delay):
                    raise Stopped from exc
                continue
            self.backoff.reset()
            self.stats.batches += 1
            self.stats.lines += len(lines)
            for k, v in (result or {}).items():
                if isinstance(v, int):
                    self.stats.accepted[k] = self.stats.accepted.get(k, 0) + v
            return

    def _split(self, lines: list[str], exc: ApiError) -> None:
        if len(lines) == 1:
            self.stats.dropped += 1
            log.error("dropping unacceptable log line (%s): %.200r", exc, lines[0])
            return
        mid = len(lines) // 2
        self._post(lines[:mid])
        self._post(lines[mid:])

    def run_once(self) -> int:
        """Ship at most one batch per file. Returns the number of lines shipped."""
        shipped = 0
        for t in self.tailers:
            lines = t.read_lines(self.batch_size)
            if not lines:
                continue
            self._post(lines)
            t.commit()
            shipped += len(lines)
        return shipped

    def run(self) -> None:
        log.info("log shipper started for %s", ", ".join(str(t.path) for t in self.tailers))
        while not self.stop.is_set():
            try:
                shipped = self.run_once()
            except Stopped:
                break
            except Exception:  # noqa: BLE001 - keep shipping whatever happens
                log.exception("log shipper iteration failed")
                shipped = 0
            if shipped == 0:
                self.stop.wait(self.flush_interval)
        for t in self.tailers:
            t.close()
