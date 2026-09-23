from __future__ import annotations

import threading

from nom_tacacs_agent.api import ApiError
from nom_tacacs_agent.backoff import Backoff
from nom_tacacs_agent.shipper import LogShipper, Stopped
from nom_tacacs_agent.tailer import FileTailer, OffsetStore


class NoWait(threading.Event):
    """Event whose wait() returns immediately (no real sleeping in tests)."""

    def __init__(self, stop_after: int | None = None):
        super().__init__()
        self.waits: list[float] = []
        self.stop_after = stop_after

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.stop_after is not None and len(self.waits) >= self.stop_after:
            self.set()
        return self.is_set()


def make(tmp_path, fake_api, lines, stop=None, batch=100):
    log = tmp_path / "acct.log"
    log.write_text("".join(f"{x}\n" for x in lines))
    store = OffsetStore(tmp_path / "offsets.json")
    t = FileTailer(log, store)
    s = LogShipper(fake_api, [t], batch_size=batch, stop=stop or NoWait(), backoff=Backoff(rand=lambda: 1.0))
    return s, t, store, log


def test_ships_and_commits(tmp_path, fake_api):
    s, t, store, log = make(tmp_path, fake_api, ["a", "b", "c"], batch=2)
    assert s.run_once() == 2
    assert s.run_once() == 1
    assert fake_api.ingested == [["a", "b"], ["c"]]
    assert store.get(str(log)).offset == 6


def test_retries_with_backoff_before_commit(tmp_path, fake_api):
    stop = NoWait()
    fake_api.ingest_results = [ApiError("down", 503), ApiError("net"), {"accounting": 2}]
    s, t, store, log = make(tmp_path, fake_api, ["a", "b"], stop=stop)
    assert s.run_once() == 2
    assert stop.waits == [1.0, 2.0]  # exponential
    assert fake_api.ingested == [["a", "b"]]
    assert s.stats.retries == 2
    assert store.get(str(log)).offset == 4


def test_stop_during_retry_does_not_commit(tmp_path, fake_api):
    stop = NoWait(stop_after=1)
    fake_api.ingest_results = [ApiError("down", 503)]
    s, t, store, log = make(tmp_path, fake_api, ["a"], stop=stop)
    try:
        s.run_once()
        raise AssertionError("expected Stopped")
    except Stopped:
        pass
    assert store.get(str(log)) is None  # will be re-read after restart


def test_poison_line_is_isolated_and_dropped(tmp_path, fake_api):
    lines = ["a", "b", "BAD", "d"]

    def ingest(batch):
        if "BAD" in batch:
            raise ApiError("unprocessable", 422)
        fake_api.ingested.append(batch)
        return {"accounting": len(batch)}

    fake_api.ingest = ingest
    s, t, store, log = make(tmp_path, fake_api, lines)
    s.run_once()
    shipped = [x for b in fake_api.ingested for x in b]
    assert shipped == ["a", "b", "d"]
    assert s.stats.dropped == 1
    assert store.get(str(log)).offset == len("a\nb\nBAD\nd\n")


def test_run_loop_exits_on_stop(tmp_path, fake_api):
    stop = NoWait(stop_after=1)
    s, t, store, log = make(tmp_path, fake_api, ["a"], stop=stop)
    s.run()
    assert fake_api.ingested == [["a"]]
