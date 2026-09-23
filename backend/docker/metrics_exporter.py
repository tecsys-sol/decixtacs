"""Prometheus exporter for Celery workers.

Celery runs tasks in prefork child processes, so the ``nom_*`` counters incremented by backup,
compliance, alerting and sync tasks live in many processes. With ``PROMETHEUS_MULTIPROC_DIR``
set (the entrypoint does this for the ``worker`` role) every process writes its samples to
memory-mapped files; this exporter aggregates them and serves ``/metrics``.

Gauges (e.g. ``nom_compliance_score``) carry a ``pid`` label in multiprocess mode; aggregate
with ``max by (tenant)`` in PromQL.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.multiprocess import MultiProcessCollector


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9808)
    p.add_argument("--addr", default="0.0.0.0")  # noqa: S104 - scraped from inside the cluster
    a = p.parse_args()
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        print("PROMETHEUS_MULTIPROC_DIR is not set", file=sys.stderr)
        return 1
    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    start_http_server(a.port, addr=a.addr, registry=registry)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    parent = os.getppid()
    while True:
        time.sleep(5)
        if os.getppid() != parent:  # celery main process went away
            return 0


if __name__ == "__main__":
    sys.exit(main())
