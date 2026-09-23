"""Pull -> verify -> validate (``tac_plus-ng -P``) -> atomic swap -> reload -> heartbeat.

The platform only serves configuration an operator explicitly deployed (``409`` otherwise), and
identifies it by its sha256 (``ETag``). The agent never runs a file that failed validation: the
candidate is written next to the live file, parsed by tac_plus-ng, and only then renamed over the
live file (``os.replace`` is atomic on POSIX). If the reload fails the previous file is restored
and reloaded, and an ``error`` heartbeat raises a ``tacacs_deploy_failed`` alert on the platform.
"""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nom_tacacs_agent.api import AgentAPI, ApiError, sha256_text

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    output: str = ""


Validator = Callable[[Path], ValidationResult]
Reloader = Callable[[], None]


class ReloadError(RuntimeError):
    pass


@dataclass
class SyncOutcome:
    action: str  # unchanged | deployed | rejected | rolled_back | not_deployed | conflict | error
    sha256: str | None = None
    message: str = ""


def file_sha256(path: Path) -> str | None:
    try:
        return sha256_text(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# --- validation / reload implementations ----------------------------------------------------


def tacplus_validator(binary: str, timeout: float = 60) -> Validator:
    """``tac_plus-ng -P <file>`` parses the configuration and exits (0 = valid)."""

    def validate(path: Path) -> ValidationResult:
        try:
            p = subprocess.run([binary, "-P", str(path)], capture_output=True, text=True, timeout=timeout,
                               check=False)
        except FileNotFoundError:
            return ValidationResult(False, f"validator binary not found: {binary}")
        except subprocess.TimeoutExpired:
            return ValidationResult(False, f"{binary} -P timed out after {timeout}s")
        out = (p.stdout + p.stderr).strip()
        return ValidationResult(p.returncode == 0, out[-4000:])

    return validate


def signal_reloader(pidfile: Path, sig: int = signal.SIGHUP, settle: float = 1.0) -> Reloader:
    """Send SIGHUP to the tac_plus-ng master (spawnd) whose pid the supervisor wrote to ``pidfile``."""

    def reload() -> None:
        try:
            pid = int(pidfile.read_text().strip())
        except (FileNotFoundError, ValueError) as exc:
            raise ReloadError(f"cannot read tac_plus-ng pid from {pidfile}: {exc}") from exc
        try:
            os.kill(pid, sig)
        except ProcessLookupError as exc:
            raise ReloadError(f"tac_plus-ng (pid {pid}) is not running") from exc
        time.sleep(settle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError as exc:
            raise ReloadError(f"tac_plus-ng (pid {pid}) exited after reload") from exc

    return reload


def command_reloader(command: str, timeout: float = 60) -> Reloader:
    """Run e.g. ``systemctl reload tac_plus-ng`` (or ``restart``) on a classic host install."""

    def reload() -> None:
        try:
            p = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReloadError(f"reload command failed: {exc}") from exc
        if p.returncode != 0:
            raise ReloadError(f"reload command exited {p.returncode}: {(p.stdout + p.stderr).strip()[-2000:]}")

    return reload


def noop_reloader() -> None:
    return None


# --- deployer --------------------------------------------------------------------------------


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_private(path: Path, content: str, mode: int = 0o640) -> None:
    """Write with restrictive permissions from the start (the file contains NAS keys)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(path, mode)


class ConfigDeployer:
    def __init__(self, api: AgentAPI, config_path: Path, validator: Validator, reloader: Reloader):
        self.api = api
        self.config_path = Path(config_path)
        self.validator = validator
        self.reloader = reloader
        self.running_sha: str | None = file_sha256(self.config_path)
        self._rejected: dict[str, str] = {}  # sha -> validator output (do not re-validate every poll)

    @property
    def candidate_path(self) -> Path:
        return self.config_path.with_name(f".{self.config_path.name}.candidate")

    @property
    def previous_path(self) -> Path:
        return self.config_path.with_name(f"{self.config_path.name}.previous")

    def _heartbeat(self, status: str, message: str) -> None:
        try:
            self.api.heartbeat(self.running_sha, status, message)
        except ApiError as exc:
            log.warning("heartbeat failed: %s", exc)

    def sync_once(self) -> SyncOutcome:
        try:
            resp = self.api.fetch_config(self.running_sha)
        except ApiError as exc:
            log.warning("config fetch failed: %s", exc)
            return SyncOutcome("error", self.running_sha, str(exc))

        if resp.state == "unchanged":
            self._heartbeat("ok", "configuration up to date")
            return SyncOutcome("unchanged", self.running_sha)
        if resp.state == "not_deployed":
            self._heartbeat("ok", "no configuration deployed yet; running bootstrap configuration")
            return SyncOutcome("not_deployed", self.running_sha, resp.detail)
        if resp.state == "conflict":
            # Pending edits were never deployed by an operator: keep running what we have.
            self._heartbeat("ok", f"keeping running configuration: {resp.detail}")
            return SyncOutcome("conflict", self.running_sha, resp.detail)

        new_sha = sha256_text(resp.content)
        if resp.etag and resp.etag != new_sha:
            msg = f"integrity check failed: ETag {resp.etag} != sha256 of body {new_sha}"
            log.error(msg)
            self._heartbeat("error", msg)
            return SyncOutcome("rejected", new_sha, msg)
        if new_sha == self.running_sha:
            self._heartbeat("ok", "configuration up to date")
            return SyncOutcome("unchanged", new_sha)
        if new_sha in self._rejected:
            msg = f"configuration {new_sha[:12]} previously rejected by tac_plus-ng -P: {self._rejected[new_sha]}"
            self._heartbeat("error", msg)
            return SyncOutcome("rejected", new_sha, msg)
        return self._deploy(resp.content, new_sha, resp.version)

    def _deploy(self, content: str, new_sha: str, version: int | None) -> SyncOutcome:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.candidate_path
        _write_private(candidate, content)

        result = self.validator(candidate)
        if not result.ok:
            self._rejected[new_sha] = result.output[-1500:]
            candidate.unlink(missing_ok=True)
            msg = f"tac_plus-ng -P rejected configuration {new_sha[:12]} (version {version}): {result.output[-1500:]}"
            log.error(msg)
            self._heartbeat("error", msg)
            return SyncOutcome("rejected", new_sha, msg)

        had_previous = self.config_path.exists()
        if had_previous:
            # Hard copy (not rename) so the live path never disappears, even for a moment.
            _write_private(self.previous_path, self.config_path.read_text(encoding="utf-8"))
        os.replace(candidate, self.config_path)
        _fsync_dir(self.config_path.parent)

        try:
            self.reloader()
        except Exception as exc:  # noqa: BLE001 - any reload failure triggers rollback
            msg = f"reload after deploying {new_sha[:12]} failed: {exc}"
            log.error(msg)
            if had_previous:
                os.replace(self.previous_path, self.config_path)
                _fsync_dir(self.config_path.parent)
                try:
                    self.reloader()
                    msg += "; rolled back to previous configuration"
                except Exception as exc2:  # noqa: BLE001
                    msg += f"; rollback reload also failed: {exc2}"
            self.running_sha = file_sha256(self.config_path)
            self._heartbeat("error", msg)
            return SyncOutcome("rolled_back", self.running_sha, msg)

        self.running_sha = new_sha
        self._rejected.clear()
        msg = f"deployed configuration version {version} ({new_sha[:12]})"
        log.info(msg)
        self._heartbeat("ok", msg)
        return SyncOutcome("deployed", new_sha, msg)
