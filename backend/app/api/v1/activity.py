"""Modules 7 (command accounting), 8 (session recording), 9 (audit), 10 (change management)."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import Ctx, get_owned, require
from app.api.v1.common import ORM, Page, paginate
from app.core.config import get_settings
from app.core.security import sha256
from app.db.session import get_db
from app.models import (
    AuditEvent,
    ChangeRequest,
    ChangeRequestComment,
    CommandLog,
    ConfigBackup,
    Device,
    SessionRecording,
    TacacsServer,
)
from app.services import audit, rancid_history
from app.services.backup.engine import device_relpath
from app.services.changes import TRANSITIONS, TransitionError, apply_transition
from app.services.risk import classify_command
from app.services.tacacs.ingest import ingest_lines

router = APIRouter(tags=["activity"])


# --- accounting ------------------------------------------------------------------------


class CommandOut(ORM):
    id: uuid.UUID
    timestamp: datetime
    username: str
    device_id: uuid.UUID | None
    device_address: str
    device_name: str | None
    source_address: str | None
    service: str | None
    record_type: str
    command: str
    result: str
    priv_lvl: int | None
    dangerous: str | None = None


@router.get("/accounting/commands", response_model=Page[CommandOut])
def search_commands(
    user: str | None = None,
    device: str | None = Query(None, description="hostname or management address"),
    device_id: uuid.UUID | None = Query(None, description="inventory device (matches its id, address and name)"),
    command: str | None = Query(None, description="substring; prefix with ~ for a regex (PostgreSQL)"),
    result: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("accounting:read")),
):
    stmt = select(CommandLog).where(CommandLog.tenant_id == ctx.tenant_id).order_by(CommandLog.timestamp.desc())
    if user:
        stmt = stmt.where(CommandLog.username == user)
    if device:
        stmt = stmt.where(or_(CommandLog.device_name == device, CommandLog.device_address == device))
    if device_id:
        dev = get_owned(ctx, Device, device_id, "device")
        stmt = stmt.where(
            or_(
                CommandLog.device_id == dev.id,
                CommandLog.device_address == dev.management_ip,
                CommandLog.device_name == dev.hostname,
            )
        )
    if command:
        stmt = stmt.where(
            CommandLog.command.regexp_match(command[1:])
            if command.startswith("~")
            else CommandLog.command.ilike(f"%{command}%")
        )
    if result:
        stmt = stmt.where(CommandLog.result == result)
    if start:
        stmt = stmt.where(CommandLog.timestamp >= start)
    if end:
        stmt = stmt.where(CommandLog.timestamp <= end)
    page = paginate(ctx.db, stmt, CommandOut, limit, offset)
    for item in page["items"]:
        item.dangerous = classify_command(item.command)
    return page


class IngestIn(BaseModel):
    lines: list[str]


@router.post("/accounting/ingest")
def ingest(body: IngestIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Log shipper endpoint. Authenticated with the TACACS server's agent token."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    server = db.scalar(select(TacacsServer).where(TacacsServer.agent_token_hash == sha256(token))) if token else None
    if server is None:
        raise HTTPException(401, "invalid agent token")
    stats = ingest_lines(db, server.tenant_id, body.lines)
    db.commit()
    return stats


@router.get("/accounting/top")
def accounting_top(days: int = 7, ctx: Ctx = Depends(require("accounting:read"))):
    from datetime import timedelta

    from app.db.base import utcnow

    since = utcnow() - timedelta(days=days)
    base = select().where(CommandLog.tenant_id == ctx.tenant_id, CommandLog.timestamp >= since)
    users = ctx.db.execute(
        base.add_columns(CommandLog.username, func.count().label("n"))
        .group_by(CommandLog.username)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    devices = ctx.db.execute(
        base.add_columns(func.coalesce(CommandLog.device_name, CommandLog.device_address), func.count())
        .group_by(func.coalesce(CommandLog.device_name, CommandLog.device_address))
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    return {
        "users": [{"user": u, "commands": n} for u, n in users],
        "devices": [{"device": d, "commands": n} for d, n in devices],
    }


# --- session recordings -------------------------------------------------------------------


class RecordingOut(ORM):
    id: uuid.UUID
    username: str
    device_id: uuid.UUID | None
    device_address: str
    source_address: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_s: float | None
    size_bytes: int
    commands: list


def _extract_commands(cast_text: str) -> tuple[list[dict], float]:
    """Pull typed lines out of an asciicast v2 stream (input 'i' events, or prompt-echo heuristics)."""
    commands: list[dict] = []
    buf = ""
    last_t = 0.0
    lines = cast_text.splitlines()
    for raw in lines[1:]:
        try:
            t, kind, data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        last_t = float(t)
        if kind != "i":
            continue
        for ch in data:
            if ch in "\r\n":
                if buf.strip():
                    commands.append({"t": round(float(t), 3), "cmd": buf.strip()})
                buf = ""
            elif ch in "\x7f\b":
                buf = buf[:-1]
            elif ch.isprintable():
                buf += ch
    return commands, last_t


@router.post("/sessions", response_model=RecordingOut, status_code=201)
async def upload_recording(
    file: UploadFile = File(..., description="asciicast v2 (.cast)"),
    username: str = Form(...),
    device_address: str = Form(...),
    source_address: str | None = Form(None),
    started_at: datetime | None = Form(None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Called by the SSH bastion/recorder (authenticated with a TACACS agent token)."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    server = db.scalar(select(TacacsServer).where(TacacsServer.agent_token_hash == sha256(token))) if token else None
    if server is None:
        raise HTTPException(401, "invalid agent token")
    data = await file.read()
    text = data.decode("utf-8", errors="replace")
    try:
        header = json.loads(text.splitlines()[0])
        assert header.get("version") == 2
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, "not an asciicast v2 file") from exc
    commands, duration = _extract_commands(text)
    rid = uuid.uuid4()
    root = Path(get_settings().backup_repo_root).parent / "recordings" / str(server.tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{rid}.cast"
    path.write_bytes(data)
    dev = db.scalar(select(Device).where(Device.tenant_id == server.tenant_id, Device.management_ip == device_address))
    # asciicast "timestamp" is a Unix epoch: convert in UTC, not the API process' local zone
    ts = started_at or (datetime.fromtimestamp(header["timestamp"], UTC) if header.get("timestamp") else None)
    rec = SessionRecording(
        id=rid,
        tenant_id=server.tenant_id,
        username=username,
        device_id=dev.id if dev else None,
        device_address=device_address,
        source_address=source_address,
        duration_s=duration,
        storage_uri=f"file://{path}",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        commands=commands,
    )
    if ts:
        rec.started_at = ts
    db.add(rec)
    db.commit()
    return rec


@router.get("/sessions", response_model=Page[RecordingOut])
def list_recordings(
    user: str | None = None,
    device_id: uuid.UUID | None = None,
    command: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("sessions:read")),
):
    from sqlalchemy import String, cast

    stmt = (
        select(SessionRecording)
        .where(SessionRecording.tenant_id == ctx.tenant_id)
        .order_by(SessionRecording.started_at.desc())
    )
    if user:
        stmt = stmt.where(SessionRecording.username == user)
    if device_id:
        stmt = stmt.where(SessionRecording.device_id == device_id)
    if command:
        stmt = stmt.where(cast(SessionRecording.commands, String).ilike(f"%{command}%"))
    return paginate(ctx.db, stmt, RecordingOut, limit, offset)


@router.get("/sessions/{rec_id}", response_model=RecordingOut)
def get_recording(rec_id: uuid.UUID, ctx: Ctx = Depends(require("sessions:read"))):
    """Recording metadata + extracted command index (viewing metadata is not audited; replay is)."""
    return get_owned(ctx, SessionRecording, rec_id, "recording")


@router.get("/sessions/{rec_id}/cast")
def get_cast(rec_id: uuid.UUID, ctx: Ctx = Depends(require("sessions:read"))):
    rec = get_owned(ctx, SessionRecording, rec_id, "recording")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="session.replay",
        actor=ctx.user,
        target_type="session_recording",
        target_id=rec.id,
        target_name=f"{rec.username}@{rec.device_address}",
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    if not rec.storage_uri.startswith("file://"):
        raise HTTPException(501, "object-storage backends are served via pre-signed URLs")
    return FileResponse(rec.storage_uri.removeprefix("file://"), media_type="application/x-asciicast")


# --- audit ------------------------------------------------------------------------------------


class AuditOut(ORM):
    id: uuid.UUID
    timestamp: datetime
    actor_name: str
    action: str
    target_type: str | None
    target_id: str | None
    target_name: str | None
    source_ip: str | None
    before: dict | None
    after: dict | None
    outcome: str


# --- user sessions (reconstructed from TACACS+ accounting) ---------------------------------------


def _summary(sessions, auths) -> dict:
    return {
        "sessions": len(sessions),
        "users": len({s.username for s in sessions}),
        "commands": sum(s.commands for s in sessions),
        "config_sessions": sum(1 for s in sessions if s.config_commands),
        "denied": sum(s.denied for s in sessions),
        "logins": sum(1 for a in auths if a.result == "pass"),
        "failed_logins": sum(1 for a in auths if a.result == "fail"),
    }


@router.get("/user-sessions")
def user_sessions(
    device_id: uuid.UUID | None = None,
    user: str | None = None,
    days: int = Query(7, ge=1, le=90),
    config_only: bool = False,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("accounting:read")),
):
    """Who logged in where and what they typed: sessions rebuilt from accounting + login events."""
    from app.services.sessions import reconstruct

    device = get_owned(ctx, Device, device_id, "device") if device_id else None
    since = datetime.now(UTC) - timedelta(days=days)
    sessions, auths = reconstruct(ctx.db, ctx.tenant_id, since=since, device=device, user=user or None)
    summary = _summary(sessions, auths)
    if config_only:
        sessions = [s for s in sessions if s.config_commands]
    return {
        "items": [s.to_dict() for s in sessions[offset : offset + limit]],
        "total": len(sessions),
        "limit": limit,
        "offset": offset,
        "summary": summary,
    }


@router.get("/devices/{device_id}/activity")
def device_activity(
    device_id: uuid.UUID, days: int = Query(30, ge=1, le=365), ctx: Ctx = Depends(require("configs:read"))
):
    """Change-history dashboard of one device: changes, backup runs, sessions and logins."""
    from app.api.v1.configs import _device
    from app.services.sessions import reconstruct

    d = _device(ctx, device_id)
    since = datetime.now(UTC) - timedelta(days=days)
    backups = list(
        ctx.db.scalars(
            select(ConfigBackup)
            .where(ConfigBackup.device_id == d.id, ConfigBackup.collected_at >= since)
            .order_by(ConfigBackup.collected_at.desc())
        )
    )
    first_change = ctx.db.scalar(
        select(func.min(ConfigBackup.collected_at)).where(ConfigBackup.device_id == d.id, ConfigBackup.changed)
    )
    changes = [b for b in backups if b.changed and b.collected_at != first_change]
    change_ids = {b.id for b in changes}
    per_day: dict[str, dict] = {}

    def day(ts) -> dict:
        k = ts.date().isoformat()
        return per_day.setdefault(k, {"day": k, "changes": 0, "sessions": 0, "commands": 0, "backups": 0, "failed": 0})

    for b in backups:
        e = day(b.collected_at)
        e["backups"] += 1
        e["failed"] += b.status == "failed"
        e["changes"] += b.id in change_ids
    rows = [
        {
            "id": str(b.id),
            "at": b.collected_at,
            "commit": b.commit_sha,
            "author": b.author,
            "reason": b.reason,
            "added": b.lines_added,
            "removed": b.lines_removed,
            "risk": b.risk_score,
            "trigger": b.trigger,
            "change_request_id": str(b.change_request_id) if b.change_request_id else None,
            "source": "nom",
        }
        for b in changes
    ]
    # revisions imported from RANCID's CVS history (older than NOM's own backups)
    rstore = rancid_history.history_store(ctx.db, ctx.tenant_id)
    if rstore is not None:
        imported = rancid_history.device_changes(rstore, device_relpath(d), since)
        for r in imported:
            day(r["at"])["changes"] += 1
        rows = sorted(rows + imported, key=lambda r: r["at"], reverse=True)
    out = {
        "device": {"id": str(d.id), "hostname": d.hostname},
        "days": days,
        "summary": {
            "changes": len(rows),
            "lines_added": sum(r["added"] for r in rows),
            "lines_removed": sum(r["removed"] for r in rows),
            "backups": len(backups),
            "failed_backups": sum(1 for b in backups if b.status == "failed"),
            "authors": len({r["author"] for r in rows if r["author"]}),
        },
        "changes": rows[:200],
        "accounting": ctx.principal.can_on_device("accounting:read", d),
        "sessions": [],
        "logins": [],
    }
    if out["accounting"]:
        sessions, auths = reconstruct(ctx.db, ctx.tenant_id, since=since, device=d)
        for s in sessions:
            e = day(s.start)
            e["sessions"] += 1
            e["commands"] += s.commands
        out["summary"].update(_summary(sessions, auths))
        out["sessions"] = [s.to_dict() for s in sessions[:200]]
        out["logins"] = [
            {"at": a.timestamp, "user": a.username, "source": a.source_address, "result": a.result, "detail": a.detail}
            for a in sorted(auths, key=lambda a: a.timestamp, reverse=True)[:300]
        ]
    out["per_day"] = sorted(per_day.values(), key=lambda e: e["day"])
    return out


@router.get("/audit", response_model=Page[AuditOut])
def list_audit(
    actor: str | None = None,
    action: str | None = Query(None, description="exact or prefix*"),
    target_type: str | None = None,
    target_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("audit:read")),
):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id).order_by(AuditEvent.timestamp.desc())
    if actor:
        stmt = stmt.where(AuditEvent.actor_name == actor)
    if action:
        stmt = stmt.where(
            AuditEvent.action.like(action[:-1] + "%") if action.endswith("*") else AuditEvent.action == action
        )
    if target_type:
        stmt = stmt.where(AuditEvent.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    if start:
        stmt = stmt.where(AuditEvent.timestamp >= start)
    if end:
        stmt = stmt.where(AuditEvent.timestamp <= end)
    return paginate(ctx.db, stmt, AuditOut, limit, offset)


@router.get("/audit/verify")
def verify_audit(ctx: Ctx = Depends(require("audit:read"))):
    ok, n = audit.verify_chain(ctx.db, ctx.tenant_id)
    return {"intact": ok, "events_verified": n}


# --- change management ------------------------------------------------------------------------


class ChangeIn(BaseModel):
    title: str
    description: str | None = None
    risk: str = "medium"
    device_ids: list[uuid.UUID] = []
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    implementation_plan: str | None = None
    rollback_plan: str | None = None
    external_ticket: str | None = None


class ChangeOut(ORM):
    id: uuid.UUID
    number: int
    title: str
    description: str | None
    state: str
    risk: str
    requested_by: uuid.UUID
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    implemented_at: datetime | None
    closed_at: datetime | None
    device_ids: list
    implementation_plan: str | None
    rollback_plan: str | None
    pre_backup_ids: list
    post_backup_ids: list
    external_ticket: str | None
    created_at: datetime


class TransitionIn(BaseModel):
    transition: str
    comment: str | None = None
    take_backup: bool = True


class CommentIn(BaseModel):
    body: str


@router.get("/changes", response_model=Page[ChangeOut])
def list_changes(
    state: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("changes:read")),
):
    stmt = select(ChangeRequest).where(ChangeRequest.tenant_id == ctx.tenant_id).order_by(ChangeRequest.number.desc())
    if state:
        stmt = stmt.where(ChangeRequest.state == state)
    if q:
        stmt = stmt.where(ChangeRequest.title.ilike(f"%{q}%"))
    return paginate(ctx.db, stmt, ChangeOut, limit, offset)


@router.post("/changes", response_model=ChangeOut, status_code=201)
def create_change(body: ChangeIn, ctx: Ctx = Depends(require("changes:write"))):
    for did in body.device_ids:
        get_owned(ctx, Device, did, "device")
    if ctx.db.bind.dialect.name == "postgresql":
        # serialise numbering per tenant (FOR UPDATE is not allowed with aggregates)
        ctx.db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"chg:{ctx.tenant_id}"})
    number = (
        ctx.db.scalar(select(func.max(ChangeRequest.number)).where(ChangeRequest.tenant_id == ctx.tenant_id)) or 0
    ) + 1
    cr = ChangeRequest(
        tenant_id=ctx.tenant_id,
        number=number,
        requested_by=ctx.user.id,
        **body.model_dump(exclude={"device_ids"}),
        device_ids=[str(d) for d in body.device_ids],
    )
    ctx.db.add(cr)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="change.create",
        actor=ctx.user,
        target_type="change_request",
        target_id=cr.id,
        target_name=f"CHG-{cr.number}",
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return cr


@router.get("/changes/{change_id}")
def get_change(change_id: uuid.UUID, ctx: Ctx = Depends(require("changes:read"))):
    cr = get_owned(ctx, ChangeRequest, change_id, "change request")
    comments = ctx.db.scalars(
        select(ChangeRequestComment)
        .where(ChangeRequestComment.change_request_id == cr.id)
        .order_by(ChangeRequestComment.created_at)
    ).all()
    backups = {b.id: b for b in ctx.db.scalars(select(ConfigBackup).where(ConfigBackup.change_request_id == cr.id))}
    return {
        "change": ChangeOut.model_validate(cr),
        "comments": [
            {
                "id": str(c.id),
                "author_id": str(c.author_id) if c.author_id else None,
                "created_at": c.created_at,
                "body": c.body,
                "transition": c.transition,
            }
            for c in comments
        ],
        "backups": [
            {
                "id": str(b.id),
                "device_id": str(b.device_id),
                "commit_sha": b.commit_sha,
                "collected_at": b.collected_at,
                "reason": b.reason,
            }
            for b in backups.values()
        ],
        "allowed_transitions": [t.name for t in TRANSITIONS.values() if cr.state in t.source],
    }


@router.patch("/changes/{change_id}", response_model=ChangeOut)
def update_change(change_id: uuid.UUID, body: ChangeIn, ctx: Ctx = Depends(require("changes:write"))):
    cr = get_owned(ctx, ChangeRequest, change_id, "change request")
    if cr.state not in ("draft", "rejected"):
        raise HTTPException(409, "only draft or rejected changes can be edited")
    before = ChangeOut.model_validate(cr).model_dump(mode="json")
    for k, v in body.model_dump(exclude={"device_ids"}).items():
        setattr(cr, k, v)
    cr.device_ids = [str(d) for d in body.device_ids]
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="change.update",
        actor=ctx.user,
        target_type="change_request",
        target_id=cr.id,
        target_name=f"CHG-{cr.number}",
        before=before,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return cr


@router.post("/changes/{change_id}/transition", response_model=ChangeOut)
def transition_change(change_id: uuid.UUID, body: TransitionIn, ctx: Ctx = Depends(require("changes:read"))):
    """Workflow: draft -> pending_approval -> approved -> implemented -> closed.
    ``approve`` snapshots pre-change backups, ``implement`` snapshots post-change backups."""
    cr = get_owned(ctx, ChangeRequest, change_id, "change request")
    before_state = cr.state
    try:
        apply_transition(cr, body.transition, ctx.user, ctx.principal.permissions)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    if body.take_backup and cr.device_ids and body.transition in ("approve", "implement"):
        from app.workers.tasks import backup_devices

        kind = "pre" if body.transition == "approve" else "post"
        try:
            backup_devices.delay(
                str(ctx.tenant_id),
                cr.device_ids,
                "change",
                f"CHG-{cr.number} {kind}-change snapshot",
                str(cr.id),
                ctx.user.username,
                kind,
            )
        except Exception:  # broker down must not block the workflow
            logging.getLogger(__name__).warning("could not queue change snapshot backup", exc_info=True)
    ctx.db.add(
        ChangeRequestComment(
            tenant_id=ctx.tenant_id,
            change_request_id=cr.id,
            author_id=ctx.user.id,
            body=body.comment or "",
            transition=f"{before_state}->{cr.state}",
        )
    )
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action=f"change.{body.transition}",
        actor=ctx.user,
        target_type="change_request",
        target_id=cr.id,
        target_name=f"CHG-{cr.number}",
        before={"state": before_state},
        after={"state": cr.state, "comment": body.comment},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    ctx.db.refresh(cr)  # pick up pre/post_backup_ids written by the snapshot task (eager/fast workers)
    return cr


@router.post("/changes/{change_id}/comments", status_code=201)
def comment_change(change_id: uuid.UUID, body: CommentIn, ctx: Ctx = Depends(require("changes:read"))):
    cr = get_owned(ctx, ChangeRequest, change_id, "change request")
    c = ChangeRequestComment(tenant_id=ctx.tenant_id, change_request_id=cr.id, author_id=ctx.user.id, body=body.body)
    ctx.db.add(c)
    ctx.db.commit()
    return {"id": str(c.id)}
