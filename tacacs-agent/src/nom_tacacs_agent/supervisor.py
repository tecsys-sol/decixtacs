"""Tiny process supervisor for the container: runs tac_plus-ng and the agent side by side.

* writes the tac_plus-ng pid to ``pidfile`` so the agent can SIGHUP it after a deploy;
* restarts either child with exponential backoff when it exits;
* installs the bootstrap configuration when no configuration exists yet (tac_plus-ng refuses to
  start without one; the agent replaces it with the deployed revision on its first poll);
* forwards SIGTERM/SIGINT to both children (graceful stop, SIGKILL after a timeout) and SIGHUP
  to tac_plus-ng.

Run it under an init that reaps zombies (the image uses ``tini``).
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from nom_tacacs_agent.backoff import Backoff
from nom_tacacs_agent.config import Settings

log = logging.getLogger(__name__)


@dataclass
class Child:
    name: str
    argv: list[str]
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    next_start: float = 0.0
    backoff: Backoff = field(default_factory=lambda: Backoff(base=1, maximum=30))


class Supervisor:
    def __init__(self, settings: Settings):
        self.s = settings
        self.stopping = False
        tac = [settings.tacplus_bin, *settings.tacplus_args, str(settings.config_path)]
        agent = [sys.executable, "-m", "nom_tacacs_agent", "run"]
        self.children = [Child("tac_plus-ng", tac), Child("agent", agent)]

    def _prepare(self) -> None:
        cfg = self.s.config_path
        cfg.parent.mkdir(parents=True, exist_ok=True)
        if not cfg.exists():
            if self.s.bootstrap_config.exists():
                shutil.copyfile(self.s.bootstrap_config, cfg)
                os.chmod(cfg, 0o640)
                log.info("installed bootstrap configuration at %s", cfg)
            else:
                log.warning("no configuration at %s and no bootstrap file %s", cfg, self.s.bootstrap_config)
        for d in (self.s.pidfile.parent, self.s.state_dir):
            d.mkdir(parents=True, exist_ok=True)
        for f in self.s.log_files:
            os.makedirs(os.path.dirname(f), exist_ok=True)

    def _start(self, c: Child) -> None:
        log.info("starting %s: %s", c.name, " ".join(c.argv))
        c.proc = subprocess.Popen(c.argv)  # noqa: S603 - argv from trusted settings
        c.started_at = time.monotonic()
        if c.name == "tac_plus-ng":
            tmp = self.s.pidfile.with_suffix(".tmp")
            tmp.write_text(f"{c.proc.pid}\n")
            os.replace(tmp, self.s.pidfile)

    def _signal(self, signum: int, _frame) -> None:
        if signum == signal.SIGHUP:
            tac = self.children[0].proc
            if tac and tac.poll() is None:
                tac.send_signal(signal.SIGHUP)
            return
        log.info("received signal %d, stopping", signum)
        self.stopping = True

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._signal)
        self._prepare()
        while not self.stopping:
            now = time.monotonic()
            for c in self.children:
                if c.proc is not None and c.proc.poll() is not None:
                    code = c.proc.returncode
                    ran = now - c.started_at
                    if ran > 60:
                        c.backoff.reset()
                    delay = c.backoff.next_delay()
                    log.error("%s exited with %s after %.0fs; restarting in %.1fs", c.name, code, ran, delay)
                    c.proc, c.next_start = None, now + delay
                if c.proc is None and now >= c.next_start and not self.stopping:
                    try:
                        self._start(c)
                    except OSError as exc:
                        delay = c.backoff.next_delay()
                        log.error("cannot start %s: %s; retrying in %.1fs", c.name, exc, delay)
                        c.next_start = now + delay
            time.sleep(0.5)
        return self._shutdown()

    def _shutdown(self, timeout: float = 10.0) -> int:
        for c in self.children:
            if c.proc and c.proc.poll() is None:
                c.proc.terminate()
        deadline = time.monotonic() + timeout
        for c in self.children:
            if not c.proc:
                continue
            try:
                c.proc.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                log.warning("%s did not stop in time; killing", c.name)
                c.proc.kill()
                c.proc.wait()
        self.s.pidfile.unlink(missing_ok=True)
        return 0
