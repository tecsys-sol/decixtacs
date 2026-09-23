"""Command line: ``nom-tacacs-agent {run,supervise,sync-once,ship-once,healthcheck,check-config}``."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path

from nom_tacacs_agent import __version__
from nom_tacacs_agent.api import AgentAPI
from nom_tacacs_agent.config import Settings
from nom_tacacs_agent.deployer import (
    ConfigDeployer,
    command_reloader,
    noop_reloader,
    signal_reloader,
    tacplus_validator,
)
from nom_tacacs_agent.recordings import RecordingUploader
from nom_tacacs_agent.shipper import LogShipper
from nom_tacacs_agent.tailer import FileTailer, OffsetStore

log = logging.getLogger("nom_tacacs_agent")


def _api(s: Settings) -> AgentAPI:
    verify: bool | str = s.ca_file if s.ca_file else s.verify_tls
    return AgentAPI(s.base_url, s.token, verify=verify, timeout=s.http_timeout)


def build_deployer(s: Settings, api: AgentAPI) -> ConfigDeployer:
    if s.reload_mode == "signal":
        reloader = signal_reloader(s.pidfile)
    elif s.reload_mode == "command":
        reloader = command_reloader(s.reload_command)
    else:
        reloader = noop_reloader
    return ConfigDeployer(api, s.config_path, tacplus_validator(s.tacplus_bin), reloader)


def build_shipper(s: Settings, api: AgentAPI, stop: threading.Event) -> LogShipper:
    store = OffsetStore(s.state_dir / "offsets.json")
    tailers = [FileTailer(p, store, start_at=s.start_at) for p in s.log_files]
    return LogShipper(api, tailers, batch_size=s.batch_size, flush_interval=s.flush_interval, stop=stop)


def _config_loop(deployer: ConfigDeployer, interval: float, stop: threading.Event) -> None:
    log.info("config loop started (every %.0fs), running sha256=%s", interval, deployer.running_sha)
    while not stop.is_set():
        try:
            outcome = deployer.sync_once()
            if outcome.action not in ("unchanged",):
                log.info("config sync: %s %s", outcome.action, outcome.message)
        except Exception:  # noqa: BLE001
            log.exception("config sync failed")
        stop.wait(interval)


def cmd_run(s: Settings) -> int:
    problems = s.validate()
    if problems:
        for p in problems:
            log.error("configuration: %s", p)
        return 78  # EX_CONFIG - the supervisor restarts us with backoff
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    api = _api(s)
    threads = [
        threading.Thread(target=_config_loop, args=(build_deployer(s, api), s.poll_interval, stop),
                         name="config", daemon=True),
        threading.Thread(target=build_shipper(s, api, stop).run, name="shipper", daemon=True),
    ]
    if s.spool_dir:
        up = RecordingUploader(api, s.spool_dir, settle_seconds=s.spool_settle_seconds, keep=s.spool_keep,
                               interval=s.spool_interval, stop=stop)
        threads.append(threading.Thread(target=up.run, name="recordings", daemon=True))
    log.info("nom-tacacs-agent %s -> %s", __version__, s.base_url)
    for t in threads:
        t.start()
    while not stop.is_set():
        stop.wait(1)
        dead = [t.name for t in threads if not t.is_alive()]
        if dead:
            log.error("worker thread(s) died: %s", ", ".join(dead))
            stop.set()
            return 1
    for t in threads:
        t.join(timeout=15)
    api.close()
    return 0


def cmd_sync_once(s: Settings) -> int:
    api = _api(s)
    outcome = build_deployer(s, api).sync_once()
    print(f"{outcome.action}: {outcome.message} (sha256={outcome.sha256})")
    return 0 if outcome.action in ("unchanged", "deployed", "not_deployed", "conflict") else 1


def cmd_ship_once(s: Settings) -> int:
    api = _api(s)
    n = build_shipper(s, api, threading.Event()).run_once()
    print(f"shipped {n} lines")
    return 0


def cmd_healthcheck(s: Settings) -> int:
    """Container health: tac_plus-ng process alive and accepting TCP connections."""
    try:
        pid = int(Path(s.pidfile).read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError) as exc:
        print(f"tac_plus-ng not running: {exc}", file=sys.stderr)
        return 1
    try:
        with socket.create_connection(("127.0.0.1", s.listen_port), timeout=3):
            pass
    except OSError as exc:
        print(f"port {s.listen_port} not accepting connections: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_check_config(s: Settings) -> int:
    problems = s.validate()
    for p in problems:
        print(f"ERROR: {p}")
    if not problems:
        print("configuration OK")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nom-tacacs-agent", description="NetworkOps Manager tac_plus-ng agent")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("command", choices=["run", "supervise", "sync-once", "ship-once", "healthcheck", "check-config"],
                   nargs="?", default="run")
    a = p.parse_args(argv)
    s = Settings.from_env()
    logging.basicConfig(level=getattr(logging, s.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    if a.command == "supervise":
        from nom_tacacs_agent.supervisor import Supervisor

        sys.exit(Supervisor(s).run())
    fn = {"run": cmd_run, "sync-once": cmd_sync_once, "ship-once": cmd_ship_once,
          "healthcheck": cmd_healthcheck, "check-config": cmd_check_config}[a.command]
    sys.exit(fn(s))


if __name__ == "__main__":
    main()
