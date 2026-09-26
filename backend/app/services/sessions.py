"""User sessions reconstructed from TACACS+ accounting and authentication logs.

TACACS+ has no "session" record: each command is accounted on its own. A session here is a run
of commands by one user on one device from one terminal line (tty/port, else client address)
with no pause longer than ``GAP``. A successful login shortly before the first command becomes
the session start; logins with no command afterwards (read-only look-arounds, accounting off)
are sessions of their own. Each session is linked to the configuration change the backups
recorded right after it, if any.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CommandLog, ConfigBackup, Device, TacacsAuthEvent

GAP = timedelta(minutes=30)  # silence that ends a session
LOGIN_LEAD = timedelta(minutes=15)  # login this long before the first command belongs to the session
CHANGE_LAG = timedelta(hours=3)  # a backup this long after the session can carry its change
MAX_ROWS = 50_000

CONFIG_CMD = re.compile(
    r"^(set |delete |deactivate |activate |rename |insert |replace |load |rollback|commit|"
    r"configure|conf t|config |no |interface |router |ip |ipv6 |vlan |switchport |shutdown|write( mem)?|copy run|/)",
    re.I,
)


def is_config_command(cmd: str) -> bool:
    return bool(CONFIG_CMD.match((cmd or "").strip()))


@dataclass
class UserSession:
    id: str
    username: str
    device_address: str
    device_id: str | None
    device_name: str | None
    source_address: str | None
    port: str | None
    start: datetime
    end: datetime
    login_at: datetime | None = None
    commands: int = 0
    config_commands: int = 0
    denied: int = 0
    first_commands: list[str] = field(default_factory=list)
    change: dict | None = None  # the config change recorded after the session

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_s"] = self.duration_s
        return d


def _sid(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def reconstruct(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime | None = None,
    device: Device | None = None,
    user: str | None = None,
    devices: dict[str, Device] | None = None,
) -> tuple[list[UserSession], list[TacacsAuthEvent]]:
    """(sessions newest first, authentication events in the window)."""
    cq = select(CommandLog).where(CommandLog.tenant_id == tenant_id, CommandLog.timestamp >= since)
    aq = select(TacacsAuthEvent).where(
        TacacsAuthEvent.tenant_id == tenant_id, TacacsAuthEvent.timestamp >= since, TacacsAuthEvent.kind == "authen"
    )
    if until is not None:
        cq = cq.where(CommandLog.timestamp <= until)
        aq = aq.where(TacacsAuthEvent.timestamp <= until)
    if device is not None:
        cq = cq.where(or_(CommandLog.device_id == device.id, CommandLog.device_address == device.management_ip))
        aq = aq.where(TacacsAuthEvent.device_address == device.management_ip)
    if user:
        cq = cq.where(CommandLog.username == user)
        aq = aq.where(TacacsAuthEvent.username == user)
    cmds = list(db.scalars(cq.order_by(CommandLog.timestamp).limit(MAX_ROWS)))
    auths = list(db.scalars(aq.order_by(TacacsAuthEvent.timestamp).limit(MAX_ROWS)))
    if devices is None:
        devices = {d.management_ip: d for d in db.scalars(select(Device).where(Device.tenant_id == tenant_id))}

    # --- group commands into sessions
    open_: dict[tuple, UserSession] = {}
    sessions: list[UserSession] = []
    seen: set[tuple] = set()
    for c in cmds:
        if (c.username, c.device_address, c.command, c.timestamp.replace(microsecond=0)) in seen:
            continue  # start + stop records of one command
        seen.add((c.username, c.device_address, c.command, c.timestamp.replace(microsecond=0)))
        key = (c.username, c.device_address, c.port or c.source_address or "")
        s = open_.get(key)
        if s is None or c.timestamp - s.end > GAP:
            dev = devices.get(c.device_address)
            s = UserSession(
                id=_sid(*key, c.timestamp.isoformat()),
                username=c.username,
                device_address=c.device_address,
                device_id=str(dev.id) if dev else (str(c.device_id) if c.device_id else None),
                device_name=dev.hostname if dev else c.device_name,
                source_address=c.source_address,
                port=c.port,
                start=c.timestamp,
                end=c.timestamp,
            )
            open_[key] = s
            sessions.append(s)
        s.end = c.timestamp
        s.commands += 1
        if c.result == "denied":
            s.denied += 1
        elif is_config_command(c.command):
            s.config_commands += 1
        if len(s.first_commands) < 3:
            s.first_commands.append(c.command)

    # --- logins: attach to the session they opened, or keep as a login-only session
    by_user_dev: dict[tuple, list[UserSession]] = {}
    for s in sessions:
        by_user_dev.setdefault((s.username, s.device_address), []).append(s)
    for a in auths:
        if a.result != "pass":
            continue
        cand = [
            s
            for s in by_user_dev.get((a.username, a.device_address), [])
            if s.start - LOGIN_LEAD <= a.timestamp <= s.end
            and (not s.source_address or not a.source_address or s.source_address == a.source_address)
        ]
        if cand:
            s = min(cand, key=lambda s: abs((s.start - a.timestamp).total_seconds()))
            if s.login_at is None or a.timestamp < s.login_at:
                s.login_at = a.timestamp
                s.start = min(s.start, a.timestamp)
            continue
        dev = devices.get(a.device_address)
        s = UserSession(
            id=_sid(a.username, a.device_address, a.source_address, a.timestamp.isoformat()),
            username=a.username,
            device_address=a.device_address,
            device_id=str(dev.id) if dev else None,
            device_name=dev.hostname if dev else None,
            source_address=a.source_address,
            port=None,
            start=a.timestamp,
            end=a.timestamp,
            login_at=a.timestamp,
        )
        sessions.append(s)
        by_user_dev.setdefault((s.username, s.device_address), []).append(s)

    # --- the configuration change each session produced
    with_changes = [s for s in sessions if s.config_commands and s.device_id]
    if with_changes:
        dev_ids = {uuid.UUID(s.device_id) for s in with_changes}
        lo = min(s.start for s in with_changes)
        hi = max(s.end for s in with_changes) + CHANGE_LAG
        # a device's first backup stores the whole config - it is not a change anyone made
        first = dict(
            db.execute(
                select(ConfigBackup.device_id, func.min(ConfigBackup.collected_at))
                .where(ConfigBackup.device_id.in_(dev_ids), ConfigBackup.changed)
                .group_by(ConfigBackup.device_id)
            ).all()
        )
        backups: dict[str, list[ConfigBackup]] = {}
        for b in db.scalars(
            select(ConfigBackup)
            .where(
                ConfigBackup.device_id.in_(dev_ids),
                ConfigBackup.changed,
                ConfigBackup.collected_at >= lo,
                ConfigBackup.collected_at <= hi,
            )
            .order_by(ConfigBackup.collected_at)
        ):
            if b.collected_at != first.get(b.device_id):
                backups.setdefault(str(b.device_id), []).append(b)
        for s in with_changes:
            b = next((b for b in backups.get(s.device_id, []) if s.start <= b.collected_at <= s.end + CHANGE_LAG), None)
            if b is not None:
                s.change = {
                    "backup_id": str(b.id),
                    "commit": b.commit_sha,
                    "at": b.collected_at,
                    "added": b.lines_added,
                    "removed": b.lines_removed,
                    "author": b.author,
                }
    sessions.sort(key=lambda s: s.start, reverse=True)
    return sessions, auths
