"""Prometheus exporter for Celery workers.

Celery runs tasks in prefork child processes, so the ``nom_*`` counters incremented by backup,
compliance, alerting and sync tasks live in many processes. With ``PROMETHEUS_MULTIPROC_DIR``
set (the entrypoint does this for the ``worker`` role) every process writes its samples to
memory-mapped files; this exporter aggregates them and serves ``/metrics``.

Counters and histograms are summed over all processes (including exited ones, so totals never go
backwards). Gauges are written per process (``gauge_all_<pid>.db``) and would carry a ``pid``
label; a long-lived child would keep reporting yesterday's ``nom_compliance_score`` next to
today's. This exporter therefore reports, per label set, only the value from the process file
written most recently and drops the ``pid`` label ("latest write wins").
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import signal
import sys
import time

from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.multiprocess import MultiProcessCollector

_GAUGE_FILE = re.compile(r"gauge_[a-z]+_(\d+)\.db$")


class LatestGaugeMultiProcessCollector:
    def __init__(self, path: str):
        self.path = path

    def collect(self):
        files = glob.glob(os.path.join(self.path, "*.db"))
        written: dict[str, float] = {}
        for f in files:
            m = _GAUGE_FILE.search(os.path.basename(f))
            if m:
                try:
                    written[m.group(1)] = os.path.getmtime(f)
                except OSError:
                    continue
        for metric in MultiProcessCollector.merge(files, accumulate=True):
            if metric.type == "gauge":
                latest: dict[tuple, tuple[float, object]] = {}
                for s in metric.samples:
                    labels = dict(s.labels)
                    pid = labels.pop("pid", None)
                    key = (s.name, tuple(sorted(labels.items())))
                    t = written.get(pid, 0.0) if pid is not None else float("inf")
                    if key not in latest or t >= latest[key][0]:
                        latest[key] = (t, s._replace(labels=labels))
                metric.samples = [v for _, v in latest.values()]
            yield metric


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9808)
    p.add_argument("--addr", default="0.0.0.0")  # noqa: S104 - scraped from inside the cluster
    a = p.parse_args()
    path = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not path:
        print("PROMETHEUS_MULTIPROC_DIR is not set", file=sys.stderr)
        return 1
    registry = CollectorRegistry()
    registry.register(LatestGaugeMultiProcessCollector(path))
    start_http_server(a.port, addr=a.addr, registry=registry)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    parent = os.getppid()
    while True:
        time.sleep(5)
        if os.getppid() != parent:  # celery main process went away
            return 0


if __name__ == "__main__":
    sys.exit(main())
