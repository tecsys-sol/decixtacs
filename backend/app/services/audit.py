"""Module 9 - audit trail with a per-tenant hash chain for tamper evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AuditEvent, User

SENSITIVE_KEYS = {"password", "password_hash", "key", "key_enc", "secret", "token", "mfa_secret_enc",
                  "password_enc", "ssh_key_enc", "enable_secret_enc", "token_enc", "target_enc", "password_crypt"}


def redact(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return {k: ("***" if k in SENSITIVE_KEYS else v) for k, v in data.items()}


def _utc(ts):
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _canonical(ev: AuditEvent) -> str:
    return json.dumps(
        {
            "ts": _utc(ev.timestamp).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "actor": ev.actor_name,
            "action": ev.action,
            "target": [ev.target_type, ev.target_id],
            "before": ev.before,
            "after": ev.after,
            "outcome": ev.outcome,
        },
        sort_keys=True,
        default=str,
    )


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor: User | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: Any = None,
    target_name: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    outcome: str = "success",
    source_ip: str | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        tenant_id=tenant_id,
        timestamp=utcnow(),
        actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else (actor_name or "system"),
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_name=target_name,
        before=redact(before),
        after=redact(after),
        outcome=outcome,
        source_ip=source_ip,
        request_id=request_id,
    )
    last = db.execute(
        select(AuditEvent.chain_hash, AuditEvent.timestamp)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.timestamp.desc())
        .limit(1)
        .with_for_update()
    ).first()
    prev = ""
    if last is not None:
        prev = last.chain_hash or ""
        last_ts = last.timestamp if last.timestamp.tzinfo else last.timestamp.replace(tzinfo=UTC)
        # keep timestamps strictly increasing so the chain order is unambiguous
        if ev.timestamp <= last_ts:
            ev.timestamp = last_ts + timedelta(microseconds=1)
    ev.chain_hash = hashlib.sha256((prev + _canonical(ev)).encode()).hexdigest()
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, tenant_id: uuid.UUID) -> tuple[bool, int]:
    """Re-compute the chain; returns (ok, events_checked)."""
    prev = ""
    n = 0
    for ev in db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.timestamp)):
        expected = hashlib.sha256((prev + _canonical(ev)).encode()).hexdigest()
        if expected != ev.chain_hash:
            return False, n
        prev = ev.chain_hash
        n += 1
    return True, n


def model_snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: _jsonable(getattr(obj, f, None)) for f in fields}


def _jsonable(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v
