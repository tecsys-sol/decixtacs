"""Persist parsed TACACS log records, correlate with inventory and raise alerts."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommandLog, Device, TacacsAuthEvent
from app.services import metrics
from app.services.alerting import emit_event
from app.services.tacacs.accounting import ParsedRecord, parse_line


def ingest_lines(db: Session, tenant_id: uuid.UUID, lines: Iterable[str]) -> dict[str, int]:
    stats = {"accounting": 0, "auth": 0, "skipped": 0}
    devices = {d.management_ip: d for d in db.scalars(select(Device).where(Device.tenant_id == tenant_id))}
    for line in lines:
        try:
            rec = parse_line(line)
        except ValueError:
            rec = None
        if rec is None:
            stats["skipped"] += 1
            continue
        dev = devices.get(rec.device_address)
        if rec.kind == "acct":
            _store_accounting(db, tenant_id, rec, dev)
            stats["accounting"] += 1
        else:
            _store_auth(db, tenant_id, rec, dev)
            stats["auth"] += 1
    db.flush()
    return stats


def _store_accounting(db: Session, tenant_id: uuid.UUID, rec: ParsedRecord, dev: Device | None) -> None:
    db.add(
        CommandLog(
            tenant_id=tenant_id,
            timestamp=rec.timestamp,
            username=rec.username,
            device_id=dev.id if dev else None,
            device_address=rec.device_address,
            device_name=dev.hostname if dev else None,
            source_address=rec.source_address,
            port=rec.port,
            service=rec.service,
            record_type=rec.record_type,
            command=rec.command,
            result="accounted",
            priv_lvl=rec.priv_lvl,
            task_id=rec.task_id,
            session_id=rec.session_id,
            raw=rec.raw,
        )
    )
    metrics.TACACS_REQUESTS.labels(kind="accounting", result="ok").inc()


def normalize_result(record_type: str) -> str:
    rt = (record_type or "").lower()
    if rt.startswith("permit"):
        return "permit"
    if rt.startswith("deny"):
        return "deny"
    if any(w in rt for w in ("fail", "denied", "reject", "locked")):
        return "fail"
    if any(w in rt for w in ("succeeded", "success", "pass", "accepted")):
        return "pass"
    return rt.split()[0] if rt else "unknown"


def _store_auth(db: Session, tenant_id: uuid.UUID, rec: ParsedRecord, dev: Device | None) -> None:
    result = normalize_result(rec.record_type)
    db.add(
        TacacsAuthEvent(
            tenant_id=tenant_id,
            timestamp=rec.timestamp,
            username=rec.username,
            device_address=rec.device_address,
            source_address=rec.source_address,
            kind=rec.kind,
            result=result,
            detail=rec.command or None,
        )
    )
    metrics.TACACS_REQUESTS.labels(kind=rec.kind, result=result).inc()
    if rec.kind == "author" and result == "deny" and rec.command:
        # Keep denied commands in the searchable command log as well
        db.add(
            CommandLog(
                tenant_id=tenant_id,
                timestamp=rec.timestamp,
                username=rec.username,
                device_id=dev.id if dev else None,
                device_address=rec.device_address,
                device_name=dev.hostname if dev else None,
                source_address=rec.source_address,
                port=rec.port,
                service=rec.service,
                record_type="author",
                command=rec.command,
                result="denied",
                raw=rec.raw,
            )
        )
        emit_event(
            db,
            tenant_id,
            "unauthorized_command",
            severity="high",
            title=f"Denied command by {rec.username} on {dev.hostname if dev else rec.device_address}",
            body=rec.command,
            device_id=dev.id if dev else None,
            dedup_key=f"unauth:{rec.username}:{rec.device_address}:{rec.command}",
        )
    if rec.kind == "authen" and result == "fail":
        metrics.LOGIN_FAILURES.labels(source="tacacs").inc()
