"""Agent settings, read from ``NOM_AGENT_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(v: str | None, default: bool) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _list(v: str | None, default: list[str]) -> list[str]:
    if v is None:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip()]


DEFAULT_LOGS = [
    "/var/log/tac_plus-ng/acct.log",
    "/var/log/tac_plus-ng/authz.log",
    "/var/log/tac_plus-ng/access.log",
]


@dataclass
class Settings:
    api_url: str = ""
    api_prefix: str = "/api/v1"
    token: str = ""
    verify_tls: bool = True
    ca_file: str | None = None
    http_timeout: float = 30.0

    config_path: Path = Path("/etc/tac_plus-ng/tac_plus-ng.cfg")
    bootstrap_config: Path = Path("/usr/local/share/nom-tacacs-agent/tac_plus-ng.bootstrap.cfg")
    tacplus_bin: str = "/usr/local/sbin/tac_plus-ng"
    tacplus_args: list[str] = field(default_factory=list)
    listen_port: int = 49
    reload_mode: str = "signal"  # signal | command | none
    reload_command: str = ""
    pidfile: Path = Path("/run/nom/tac_plus-ng.pid")
    poll_interval: float = 30.0

    log_files: list[str] = field(default_factory=lambda: list(DEFAULT_LOGS))
    start_at: str = "beginning"  # beginning | end (for files never seen before)
    batch_size: int = 500
    flush_interval: float = 2.0

    spool_dir: Path | None = Path("/var/spool/nom-recordings")
    spool_settle_seconds: float = 10.0
    spool_keep: bool = False
    spool_interval: float = 15.0

    state_dir: Path = Path("/var/lib/nom-agent")
    log_level: str = "INFO"

    @property
    def base_url(self) -> str:
        return self.api_url.rstrip("/") + self.api_prefix

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ if env is None else env)

        def g(name: str, default: str | None = None) -> str | None:
            return e.get(f"NOM_AGENT_{name}", default)

        token = g("TOKEN", "") or ""
        token_file = g("TOKEN_FILE")
        if token_file:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        spool = g("SPOOL_DIR", "/var/spool/nom-recordings")
        return cls(
            api_url=g("API_URL", "") or "",
            api_prefix=g("API_PREFIX", "/api/v1") or "/api/v1",
            token=token,
            verify_tls=_bool(g("VERIFY_TLS"), True),
            ca_file=g("CA_FILE") or None,
            http_timeout=float(g("HTTP_TIMEOUT", "30")),
            config_path=Path(g("CONFIG_PATH", "/etc/tac_plus-ng/tac_plus-ng.cfg")),
            bootstrap_config=Path(g("BOOTSTRAP_CONFIG",
                                    "/usr/local/share/nom-tacacs-agent/tac_plus-ng.bootstrap.cfg")),
            tacplus_bin=g("TACPLUS_BIN", "/usr/local/sbin/tac_plus-ng"),
            tacplus_args=(g("TACPLUS_ARGS", "") or "").split(),
            listen_port=int(g("LISTEN_PORT", "49")),
            reload_mode=(g("RELOAD_MODE", "signal") or "signal").lower(),
            reload_command=g("RELOAD_COMMAND", "") or "",
            pidfile=Path(g("PIDFILE", "/run/nom/tac_plus-ng.pid")),
            poll_interval=float(g("POLL_INTERVAL", "30")),
            log_files=_list(g("LOG_FILES"), DEFAULT_LOGS),
            start_at=(g("START_AT", "beginning") or "beginning").lower(),
            batch_size=int(g("BATCH_SIZE", "500")),
            flush_interval=float(g("FLUSH_INTERVAL", "2")),
            spool_dir=Path(spool) if spool else None,
            spool_settle_seconds=float(g("SPOOL_SETTLE_SECONDS", "10")),
            spool_keep=_bool(g("SPOOL_KEEP"), False),
            spool_interval=float(g("SPOOL_INTERVAL", "15")),
            state_dir=Path(g("STATE_DIR", "/var/lib/nom-agent")),
            log_level=(g("LOG_LEVEL", "INFO") or "INFO").upper(),
        )

    def validate(self) -> list[str]:
        problems = []
        if not self.api_url:
            problems.append("NOM_AGENT_API_URL is not set")
        if not self.token:
            problems.append("NOM_AGENT_TOKEN / NOM_AGENT_TOKEN_FILE is not set "
                            "(create the server with POST /api/v1/tacacs/servers to obtain one)")
        if self.reload_mode not in ("signal", "command", "none"):
            problems.append("NOM_AGENT_RELOAD_MODE must be signal, command or none")
        if self.reload_mode == "command" and not self.reload_command:
            problems.append("NOM_AGENT_RELOAD_COMMAND is required with RELOAD_MODE=command")
        if self.start_at not in ("beginning", "end"):
            problems.append("NOM_AGENT_START_AT must be beginning or end")
        if self.batch_size < 1:
            problems.append("NOM_AGENT_BATCH_SIZE must be >= 1")
        return problems
