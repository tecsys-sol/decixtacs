"""Backup orchestration: collect -> sanitise -> commit to Git -> record -> index -> analyse."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import (
    ChangeRequest,
    CommandLog,
    ConfigBackup,
    ConfigIndexEntry,
    Device,
    DriftEvent,
    GoldenConfig,
    Tenant,
)
from app.services import diff as diffsvc
from app.services import metrics
from app.services.alerting import emit_event
from app.services.backup.collector import Collector, CollectResult, CollectTarget, nornir_collect
from app.services.backup.git_store import GitConfigStore
from app.services.backup.sanitize import prepare
from app.services.drift import compare_golden
from app.services.intel.parser import parse
from app.services.risk import analyse_diff

log = logging.getLogger(__name__)

CONFIG_COMMANDS = re.compile(
    r"^(commit|configure|conf t|config|write( mem)?|copy run|end|rollback|load |set |delete |edit |/)", re.I
)


def store_for(db: Session, tenant_id: uuid.UUID) -> GitConfigStore:
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    return GitConfigStore(get_settings().backup_repo_root, tenant.slug)


def device_relpath(device: Device) -> str:
    return GitConfigStore.relpath(device.site.slug if device.site else None, device.hostname)


def build_target(device: Device) -> CollectTarget | None:
    if not device.platform or not device.credential:
        return None
    cred = device.credential
    return CollectTarget(
        device_id=str(device.id),
        hostname=device.hostname,
        host=device.management_ip,
        port=device.ssh_port,
        platform=device.platform.slug,
        scrapli_platform=device.platform.scrapli_platform,
        netmiko_device_type=device.platform.netmiko_device_type,
        commands=device.platform.backup_commands or [],
        username=cred.username,
        password=decrypt_secret(cred.password_enc),
        ssh_key=decrypt_secret(cred.ssh_key_enc),
        enable_secret=decrypt_secret(cred.enable_secret_enc),
    )


def correlate_author(db: Session, device: Device, since) -> tuple[str | None, str | None]:
    """Find who changed the device: last config-mode command in TACACS accounting since the last backup."""
    q = (
        select(CommandLog)
        .where(
            CommandLog.tenant_id == device.tenant_id,
            CommandLog.device_address == device.management_ip,
            CommandLog.timestamp >= since,
        )
        .order_by(CommandLog.timestamp.desc())
        .limit(500)
    )
    for row in db.scalars(q):
        if CONFIG_COMMANDS.search(row.command):
            m = re.search(r'commit .*comment "?([^"]+)"?', row.command)
            return row.username, (m.group(1) if m else None)
    return None, None


def run_backups(
    db: Session,
    tenant_id: uuid.UUID,
    device_ids: list[uuid.UUID] | None = None,
    *,
    collector: Collector | None = None,
    trigger: str = "schedule",
    reason: str | None = None,
    change_request_id: uuid.UUID | None = None,
    requested_by: str | None = None,
) -> list[ConfigBackup]:
    q = (
        select(Device)
        .where(Device.tenant_id == tenant_id, Device.backup_enabled, Device.status == "active")
        .options(selectinload(Device.platform), selectinload(Device.credential), selectinload(Device.site))
    )
    if device_ids:
        q = q.where(Device.id.in_(device_ids))
    devices = {str(d.id): d for d in db.scalars(q)}
    targets, backups = [], []
    for d in devices.values():
        t = build_target(d)
        if t is None:
            backups.append(_record_failure(db, d, "device has no platform or credential assigned", trigger))
        else:
            targets.append(t)
    if targets:
        results = (collector or (lambda ts: nornir_collect(ts, get_settings().backup_concurrency)))(targets)
        for r in results:
            dev = devices[r.device_id]
            backups.append(process_result(db, dev, r, trigger=trigger, reason=reason,
                                          change_request_id=change_request_id, requested_by=requested_by))
    db.flush()
    return backups


def _record_failure(db: Session, device: Device, error: str, trigger: str) -> ConfigBackup:
    b = ConfigBackup(tenant_id=device.tenant_id, device_id=device.id, status="failed", error=error, trigger=trigger)
    db.add(b)
    device.last_backup_status = "failed"
    metrics.BACKUPS.labels(status="failed", platform=device.platform.slug if device.platform else "unknown").inc()
    emit_event(db, device.tenant_id, "backup_failed", severity="medium", title=f"Backup failed: {device.hostname}",
               body=error, device_id=device.id, dedup_key=f"backup_failed:{device.id}")
    if re.search(r"timed? ?out|unreachable|no route|refused", error, re.I):
        device.reachability = "down"
        emit_event(db, device.tenant_id, "device_unreachable", severity="high",
                   title=f"Device unreachable: {device.hostname}", body=error, device_id=device.id,
                   dedup_key=f"unreachable:{device.id}")
    return b


def process_result(
    db: Session,
    device: Device,
    result: CollectResult,
    *,
    trigger: str = "schedule",
    reason: str | None = None,
    change_request_id: uuid.UUID | None = None,
    requested_by: str | None = None,
) -> ConfigBackup:
    platform = device.platform.slug if device.platform else "unknown"
    if not result.ok:
        return _record_failure(db, device, result.error or "unknown error", trigger)

    metrics.BACKUP_DURATION.labels(platform=platform).observe(result.duration_ms / 1000)
    store = store_for(db, device.tenant_id)
    relpath = device_relpath(device)
    content = prepare(result.config, platform, get_settings().backup_sanitize_secrets)
    previous = store.read(relpath) or ""

    last = db.scalar(
        select(ConfigBackup).where(ConfigBackup.device_id == device.id, ConfigBackup.status != "failed")
        .order_by(ConfigBackup.collected_at.desc()).limit(1)
    )
    # Correlate against accounting since the last *change* we recorded (log timestamps are only
    # second-precise, so using the last unchanged poll could miss the commit).
    last_change = db.scalar(
        select(ConfigBackup.collected_at).where(ConfigBackup.device_id == device.id, ConfigBackup.changed)
        .order_by(ConfigBackup.collected_at.desc()).limit(1)
    )
    since = (last_change - timedelta(seconds=1)) if last_change else utcnow() - timedelta(days=1)
    author, commit_comment = correlate_author(db, device, since)
    cr = db.get(ChangeRequest, change_request_id) if change_request_id else None
    why = reason or (f"CHG-{cr.number}: {cr.title}" if cr else None) or commit_comment or (
        "Configuration change detected" if previous else "Initial backup")
    author_name = author or requested_by or "networkops-backup"

    sha = store.write(
        relpath,
        content,
        author=author_name,
        author_email=None,
        subject=f"{device.hostname}: {why}",
        trailers={
            "Device": device.hostname,
            "Management-IP": device.management_ip,
            "Reason": why,
            "Change-Request": f"CHG-{cr.number}" if cr else "",
            "Trigger": trigger,
        },
    )
    now = utcnow()
    backup = ConfigBackup(
        tenant_id=device.tenant_id,
        device_id=device.id,
        collected_at=now,
        status="success" if sha else "unchanged",
        changed=bool(sha),
        commit_sha=sha or (last.commit_sha if last and last.commit_sha else store.last_commit(relpath)),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        author=author_name if sha else None,
        reason=why if sha else None,
        trigger=trigger,
        change_request_id=change_request_id,
        duration_ms=result.duration_ms,
    )
    if sha:
        st = diffsvc.stats(previous, content)
        backup.lines_added, backup.lines_removed = st.added, st.removed
        if previous:
            backup.risk_score = analyse_diff(diffsvc.unified(previous, content)).score
    db.add(backup)
    db.flush()
    device.last_backup_at = now
    device.last_backup_status = "success"
    device.reachability = "up"
    device.last_seen_at = now
    metrics.BACKUPS.labels(status=backup.status, platform=platform).inc()

    if sha:
        reindex(db, device, content, backup.id)
        check_golden_drift(db, device, content)
        if previous and not cr and trigger != "change":
            # A change nobody announced through a change request - surface it.
            emit_event(db, device.tenant_id, "config_drift", severity="low",
                       title=f"Unplanned config change on {device.hostname} by {author_name}",
                       body=f"+{backup.lines_added} / -{backup.lines_removed} lines. {why}",
                       device_id=device.id, dedup_key=f"unplanned:{device.id}:{sha}")
    return backup


def reindex(db: Session, device: Device, content: str, backup_id: uuid.UUID | None) -> int:
    db.execute(delete(ConfigIndexEntry).where(ConfigIndexEntry.device_id == device.id))
    objs = parse(content, device.platform.slug if device.platform else "")
    db.add_all(
        ConfigIndexEntry(tenant_id=device.tenant_id, device_id=device.id, backup_id=backup_id,
                         kind=o.kind, key=o.key[:255], attributes=o.attributes)
        for o in objs
    )
    return len(objs)


def check_golden_drift(db: Session, device: Device, content: str) -> list[DriftEvent]:
    group_ids = [g.id for g in device.groups]
    q = select(GoldenConfig).where(GoldenConfig.tenant_id == device.tenant_id)
    events = []
    for gc in db.scalars(q):
        if gc.device_id != device.id and gc.device_group_id not in group_ids:
            continue
        res = compare_golden(content, gc.content, gc.mode, gc.ignore_patterns)
        if res.drifted:
            ev = DriftEvent(tenant_id=device.tenant_id, device_id=device.id, kind="backup_vs_golden", diff=res.diff)
            db.add(ev)
            events.append(ev)
            metrics.DRIFT_EVENTS.labels(kind="backup_vs_golden").inc()
            emit_event(db, device.tenant_id, "config_drift", severity="medium",
                       title=f"{device.hostname} drifted from golden config '{gc.name}'",
                       body=res.diff[:4000], device_id=device.id, dedup_key=f"golden:{device.id}:{gc.id}")
    return events
