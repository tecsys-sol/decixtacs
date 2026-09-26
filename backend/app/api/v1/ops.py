"""Modules 14-18 + 20: integrations, route servers, alerting, reports, dashboard, global search."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import Ctx, get_owned, require
from app.api.v1.common import ORM, Page, paginate
from app.core.security import decrypt_secret, encrypt_secret
from app.db.base import utcnow
from app.models import (
    Alert,
    AlertChannel,
    AlertRule,
    AuditEvent,
    ChangeRequest,
    CommandLog,
    ComplianceRun,
    ConfigBackup,
    Device,
    ExternalObject,
    Integration,
    IxpMember,
    ReportSchedule,
    RouteServerClient,
    Site,
    TacacsAuthEvent,
    User,
    Vendor,
)
from app.services import audit, reports
from app.services.alerting import EVENT_TYPES, send

router = APIRouter(tags=["operations"])


# --- integrations ------------------------------------------------------------------------


class IntegrationIn(BaseModel):
    kind: str  # netbox | ixpmanager | birdseye
    name: str
    base_url: str
    token: str | None = None
    options: dict = {}
    enabled: bool = True


class IntegrationOut(ORM):
    id: uuid.UUID
    kind: str
    name: str
    base_url: str
    options: dict
    enabled: bool
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_detail: dict | None


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(ctx: Ctx = Depends(require("devices:read"))):
    return ctx.db.scalars(select(Integration).where(Integration.tenant_id == ctx.tenant_id)).all()


@router.post("/integrations", response_model=IntegrationOut, status_code=201)
def create_integration(body: IntegrationIn, ctx: Ctx = Depends(require("integrations:write"))):
    if body.kind not in ("netbox", "ixpmanager", "birdseye"):
        raise HTTPException(422, "kind must be netbox, ixpmanager or birdseye")
    i = Integration(tenant_id=ctx.tenant_id, token_enc=encrypt_secret(body.token), **body.model_dump(exclude={"token"}))
    ctx.db.add(i)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="integration.create",
        actor=ctx.user,
        target_type="integration",
        target_id=i.id,
        target_name=i.name,
        after=body.model_dump(exclude={"token"}),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return i


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: uuid.UUID, ctx: Ctx = Depends(require("integrations:write"))):
    i = get_owned(ctx, Integration, integration_id, "integration")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="integration.delete",
        actor=ctx.user,
        target_type="integration",
        target_id=i.id,
        target_name=i.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(i)
    ctx.db.commit()


@router.post("/integrations/{integration_id}/sync")
def sync_integration(
    integration_id: uuid.UUID, run_async: bool = True, ctx: Ctx = Depends(require("integrations:write"))
):
    i = get_owned(ctx, Integration, integration_id, "integration")
    if run_async:
        from app.workers.tasks import sync_integration as task

        return {"task_id": task.delay(str(i.id)).id}
    from app.workers.tasks import run_integration_sync

    stats = run_integration_sync(ctx.db, i)
    ctx.db.commit()
    return stats


@router.get("/ixp/members")
def ixp_members(q: str | None = None, ctx: Ctx = Depends(require("devices:read"))):
    stmt = select(IxpMember).where(IxpMember.tenant_id == ctx.tenant_id).order_by(IxpMember.name)
    if q:
        stmt = stmt.where(or_(IxpMember.name.ilike(f"%{q}%"), cast(IxpMember.asn, String) == q.removeprefix("AS")))
    return [
        {
            "id": str(m.id),
            "asn": m.asn,
            "name": m.name,
            "url": m.url,
            "peering_policy": m.peering_policy,
            "member_type": m.member_type,
            "contacts": m.contacts,
            "connections": m.connections,
            "traffic": m.traffic,
        }
        for m in ctx.db.scalars(stmt)
    ]


@router.get("/ixp/route-server-clients")
def rs_clients(asn: int | None = None, only_problems: bool = False, ctx: Ctx = Depends(require("devices:read"))):
    stmt = (
        select(RouteServerClient)
        .where(RouteServerClient.tenant_id == ctx.tenant_id)
        .order_by(RouteServerClient.asn, RouteServerClient.route_server)
    )
    if asn:
        stmt = stmt.where(RouteServerClient.asn == asn)
    if only_problems:
        stmt = stmt.where(or_(RouteServerClient.state != "up", RouteServerClient.prefixes_filtered > 0))
    names = {m.asn: m.name for m in ctx.db.scalars(select(IxpMember).where(IxpMember.tenant_id == ctx.tenant_id))}
    return [
        {
            "id": str(c.id),
            "route_server": c.route_server,
            "protocol": c.protocol_name,
            "asn": c.asn,
            "member": names.get(c.asn),
            "neighbor": c.neighbor_address,
            "afi": c.address_family,
            "state": c.state,
            "accepted": c.prefixes_accepted,
            "filtered": c.prefixes_filtered,
            "exported": c.prefixes_exported,
            "irr_filtered": c.irr_filtered,
            "rpki_invalid": c.rpki_invalid,
            "rpki": c.rpki_status,
            "irr_status": c.irr_status,
            "since": c.since,
        }
        for c in ctx.db.scalars(stmt)
    ]


@router.get("/external-objects")
def external_objects(
    object_type: str,
    q: str | None = None,
    limit: int = Query(100, le=1000),
    ctx: Ctx = Depends(require("devices:read")),
):
    stmt = (
        select(ExternalObject)
        .where(ExternalObject.tenant_id == ctx.tenant_id, ExternalObject.object_type == object_type)
        .order_by(ExternalObject.display)
    )
    if q:
        stmt = stmt.where(ExternalObject.display.ilike(f"%{q}%"))
    return [
        {"id": str(o.id), "source": o.source, "external_id": o.external_id, "display": o.display, "data": o.data}
        for o in ctx.db.scalars(stmt.limit(limit))
    ]


# --- alerting -----------------------------------------------------------------------------


class ChannelIn(BaseModel):
    name: str
    kind: str  # email|slack|teams|webhook
    target: str
    enabled: bool = True


class ChannelOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    enabled: bool


class RuleIn(BaseModel):
    name: str
    event_type: str
    min_severity: str = "low"
    channel_ids: list[uuid.UUID]
    filters: dict = {}
    throttle_minutes: int = 15
    enabled: bool = True


class RuleOut(ORM):
    id: uuid.UUID
    name: str
    event_type: str
    min_severity: str
    channel_ids: list
    filters: dict
    throttle_minutes: int
    enabled: bool


class AlertOut(ORM):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    severity: str
    title: str
    body: str | None
    device_id: uuid.UUID | None
    delivered: list
    acknowledged_at: datetime | None


@router.get("/alerts/channels", response_model=list[ChannelOut])
def list_channels(ctx: Ctx = Depends(require("alerts:write"))):
    return ctx.db.scalars(select(AlertChannel).where(AlertChannel.tenant_id == ctx.tenant_id)).all()


@router.post("/alerts/channels", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelIn, ctx: Ctx = Depends(require("alerts:write"))):
    if body.kind not in ("email", "slack", "teams", "webhook"):
        raise HTTPException(422, "kind must be email, slack, teams or webhook")
    c = AlertChannel(
        tenant_id=ctx.tenant_id,
        name=body.name,
        kind=body.kind,
        target_enc=encrypt_secret(body.target),
        enabled=body.enabled,
    )
    ctx.db.add(c)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="alert_channel.create",
        actor=ctx.user,
        target_type="alert_channel",
        target_id=c.id,
        target_name=c.name,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return c


@router.post("/alerts/channels/{channel_id}/test")
def test_channel(channel_id: uuid.UUID, ctx: Ctx = Depends(require("alerts:write"))):
    c = get_owned(ctx, AlertChannel, channel_id, "channel")
    try:
        send(
            c.kind,
            decrypt_secret(c.target_enc) or "",
            "NetworkOps Manager test alert",
            "If you can read this, the channel works.",
            "info",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"delivery failed: {e}") from e
    return {"ok": True}


@router.delete("/alerts/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: uuid.UUID, ctx: Ctx = Depends(require("alerts:write"))):
    c = get_owned(ctx, AlertChannel, channel_id, "channel")
    ctx.db.delete(c)
    ctx.db.commit()


@router.get("/alerts/rules", response_model=list[RuleOut])
def list_alert_rules(ctx: Ctx = Depends(require("alerts:write"))):
    return ctx.db.scalars(select(AlertRule).where(AlertRule.tenant_id == ctx.tenant_id)).all()


@router.post("/alerts/rules", response_model=RuleOut, status_code=201)
def create_alert_rule(body: RuleIn, ctx: Ctx = Depends(require("alerts:write"))):
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(422, f"event_type must be one of {sorted(EVENT_TYPES)}")
    for cid in body.channel_ids:
        get_owned(ctx, AlertChannel, cid, "channel")
    r = AlertRule(
        tenant_id=ctx.tenant_id,
        **body.model_dump(exclude={"channel_ids"}),
        channel_ids=[str(c) for c in body.channel_ids],
    )
    ctx.db.add(r)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="alert_rule.create",
        actor=ctx.user,
        target_type="alert_rule",
        target_id=r.id,
        target_name=r.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return r


@router.delete("/alerts/rules/{rule_id}", status_code=204)
def delete_alert_rule(rule_id: uuid.UUID, ctx: Ctx = Depends(require("alerts:write"))):
    r = get_owned(ctx, AlertRule, rule_id, "rule")
    ctx.db.delete(r)
    ctx.db.commit()


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    event_type: str | None = None,
    severity: str | None = None,
    unacknowledged: bool = False,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("devices:read")),
):
    stmt = select(Alert).where(Alert.tenant_id == ctx.tenant_id).order_by(Alert.created_at.desc())
    if event_type:
        stmt = stmt.where(Alert.event_type == event_type)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if unacknowledged:
        stmt = stmt.where(Alert.acknowledged_at.is_(None))
    return paginate(ctx.db, stmt, AlertOut, limit, offset)


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def ack_alert(alert_id: uuid.UUID, ctx: Ctx = Depends(require("devices:read"))):
    a = get_owned(ctx, Alert, alert_id, "alert")
    a.acknowledged_by, a.acknowledged_at = ctx.user.id, utcnow()
    ctx.db.commit()
    return a


# --- reports --------------------------------------------------------------------------------


@router.get("/reports/{report_type}")
def generate_report(
    report_type: str,
    period: str = "daily",
    fmt: str = "json",
    end: datetime | None = None,
    ctx: Ctx = Depends(require("reports:read")),
):
    if report_type not in reports.REPORT_TYPES or period not in reports.PERIODS:
        raise HTTPException(422, f"report_type in {reports.REPORT_TYPES}, period in {list(reports.PERIODS)}")
    r = reports.build(ctx.db, ctx.tenant_id, report_type, period, end)
    if fmt == "json":
        return {
            "title": r.title,
            "columns": r.columns,
            "rows": [[reports._cell(c) if isinstance(c, datetime) else c for c in row] for row in r.rows],
            "start": r.start,
            "end": r.end,
        }
    if fmt not in reports.RENDERERS:
        raise HTTPException(422, "fmt must be json, csv, xlsx or pdf")
    fn, mime = reports.RENDERERS[fmt]
    fname = f"{report_type}-{period}-{r.end:%Y%m%d}.{fmt}"
    return Response(fn(r), media_type=mime, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class ScheduleIn(BaseModel):
    name: str
    report_type: str
    period: str
    fmt: str = "pdf"
    recipients: list[str]
    enabled: bool = True


@router.get("/report-schedules")
def list_schedules(ctx: Ctx = Depends(require("reports:read"))):
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "report_type": s.report_type,
            "period": s.period,
            "fmt": s.fmt,
            "recipients": s.recipients,
            "enabled": s.enabled,
            "last_run_at": s.last_run_at,
        }
        for s in ctx.db.scalars(select(ReportSchedule).where(ReportSchedule.tenant_id == ctx.tenant_id))
    ]


@router.post("/report-schedules", status_code=201)
def create_schedule(body: ScheduleIn, ctx: Ctx = Depends(require("reports:read", "alerts:write"))):
    if (
        body.report_type not in reports.REPORT_TYPES
        or body.period not in reports.PERIODS
        or body.fmt not in reports.RENDERERS
    ):
        raise HTTPException(422, "invalid report_type / period / fmt")
    s = ReportSchedule(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(s)
    ctx.db.commit()
    return {"id": str(s.id)}


# --- dashboard --------------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(require("devices:read"))):
    t = ctx.tenant_id
    db = ctx.db
    now = utcnow()
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)
    total = db.scalar(select(func.count()).select_from(Device).where(Device.tenant_id == t)) or 0
    by_vendor = db.execute(
        select(func.coalesce(Vendor.name, "Unknown"), func.count())
        .select_from(Device)
        .outerjoin(Vendor, Vendor.id == Device.vendor_id)
        .where(Device.tenant_id == t)
        .group_by(Vendor.name)
    ).all()
    by_status = db.execute(
        select(Device.reachability, func.count()).where(Device.tenant_id == t).group_by(Device.reachability)
    ).all()
    by_site = db.execute(
        select(func.coalesce(Site.name, "Unassigned"), func.count())
        .select_from(Device)
        .outerjoin(Site, Site.id == Device.site_id)
        .where(Device.tenant_id == t)
        .group_by(Site.name)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    last_backup = db.scalar(
        select(func.max(ConfigBackup.collected_at)).where(ConfigBackup.tenant_id == t, ConfigBackup.status != "failed")
    )
    failures_24h = (
        db.scalar(
            select(func.count())
            .select_from(ConfigBackup)
            .where(ConfigBackup.tenant_id == t, ConfigBackup.status == "failed", ConfigBackup.collected_at >= day)
        )
        or 0
    )
    backups_24h = (
        db.scalar(
            select(func.count())
            .select_from(ConfigBackup)
            .where(ConfigBackup.tenant_id == t, ConfigBackup.collected_at >= day)
        )
        or 0
    )
    failing_devices = (
        db.scalar(
            select(func.count()).select_from(Device).where(Device.tenant_id == t, Device.last_backup_status == "failed")
        )
        or 0
    )
    runs = db.scalars(
        select(ComplianceRun)
        .where(ComplianceRun.tenant_id == t, ComplianceRun.score.is_not(None))
        .order_by(ComplianceRun.started_at.desc())
        .limit(30)
    ).all()
    top_users = db.execute(
        select(CommandLog.username, func.count())
        .where(CommandLog.tenant_id == t, CommandLog.timestamp >= week)
        .group_by(CommandLog.username)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    dev_col = func.coalesce(CommandLog.device_name, CommandLog.device_address)
    top_devices = db.execute(
        select(dev_col, func.count())
        .where(CommandLog.tenant_id == t, CommandLog.timestamp >= week)
        .group_by(dev_col)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    tacacs = db.execute(
        select(TacacsAuthEvent.result, func.count())
        .where(TacacsAuthEvent.tenant_id == t, TacacsAuthEvent.timestamp >= day)
        .group_by(TacacsAuthEvent.result)
    ).all()
    acct_24h = (
        db.scalar(
            select(func.count()).select_from(CommandLog).where(CommandLog.tenant_id == t, CommandLog.timestamp >= day)
        )
        or 0
    )
    # A device's first backup records the whole config as "added" - it is not a change.
    earlier = aliased(ConfigBackup)
    first_backup = (
        select(earlier.id)
        .where(
            earlier.device_id == ConfigBackup.device_id,
            earlier.changed,
            earlier.collected_at < ConfigBackup.collected_at,
        )
        .exists()
    )
    changes = db.execute(
        select(ConfigBackup, Device.hostname)
        .join(Device, Device.id == ConfigBackup.device_id)
        .where(ConfigBackup.tenant_id == t, ConfigBackup.changed, first_backup)
        .order_by(ConfigBackup.collected_at.desc())
        .limit(10)
    ).all()
    audits = db.scalars(
        select(AuditEvent).where(AuditEvent.tenant_id == t).order_by(AuditEvent.timestamp.desc()).limit(10)
    ).all()
    open_changes = (
        db.scalar(
            select(func.count())
            .select_from(ChangeRequest)
            .where(ChangeRequest.tenant_id == t, ChangeRequest.state.in_(["pending_approval", "approved"]))
        )
        or 0
    )
    open_alerts = (
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.tenant_id == t, Alert.acknowledged_at.is_(None), Alert.created_at >= week)
        )
        or 0
    )
    return {
        "devices": {
            "total": total,
            "by_vendor": [{"name": n, "count": c} for n, c in by_vendor],
            "by_reachability": dict(by_status),
            "by_site": [{"name": n, "count": c} for n, c in by_site],
        },
        "backups": {
            "last": last_backup,
            "last_24h": backups_24h,
            "failures_24h": failures_24h,
            "devices_failing": failing_devices,
        },
        "compliance": {
            "score": runs[0].score if runs else None,
            "trend": [{"t": r.started_at, "score": r.score} for r in reversed(runs)],
        },
        "tacacs": {"auth_24h": dict(tacacs), "accounting_24h": acct_24h},
        "top_users": [{"user": u, "commands": c} for u, c in top_users],
        "top_devices": [{"device": d, "commands": c} for d, c in top_devices],
        "recent_changes": [
            {
                "id": str(b.id),
                "device_id": str(b.device_id),
                "device": h,
                "at": b.collected_at,
                "author": b.author,
                "reason": b.reason,
                "added": b.lines_added,
                "removed": b.lines_removed,
                "risk": b.risk_score,
                "commit": b.commit_sha,
            }
            for b, h in changes
        ],
        "recent_audit": [
            {"at": a.timestamp, "actor": a.actor_name, "action": a.action, "target": a.target_name} for a in audits
        ],
        "open_changes": open_changes,
        "open_alerts": open_alerts,
    }


# --- global search ---------------------------------------------------------------------------


@router.get("/search")
def global_search(q: str = Query(..., min_length=2), ctx: Ctx = Depends(require("devices:read"))):
    t = ctx.tenant_id
    like = f"%{q}%"
    out: list[dict] = []
    for d in ctx.db.scalars(
        select(Device)
        .where(
            Device.tenant_id == t,
            or_(Device.hostname.ilike(like), Device.management_ip.ilike(like), Device.serial.ilike(like)),
        )
        .limit(10)
    ):
        out.append(
            {
                "type": "device",
                "id": str(d.id),
                "title": d.hostname,
                "subtitle": d.management_ip,
                "href": f"/devices/{d.id}",
            }
        )
    for s in ctx.db.scalars(select(Site).where(Site.tenant_id == t, Site.name.ilike(like)).limit(5)):
        out.append(
            {"type": "site", "id": str(s.id), "title": s.name, "subtitle": s.kind, "href": f"/devices?site={s.id}"}
        )
    if ctx.principal.has("users:read"):
        for u in ctx.db.scalars(
            select(User).where(User.tenant_id == t, or_(User.username.ilike(like), User.full_name.ilike(like))).limit(5)
        ):
            out.append(
                {
                    "type": "user",
                    "id": str(u.id),
                    "title": u.username,
                    "subtitle": u.full_name or "",
                    "href": f"/users/{u.id}",
                }
            )
    if ctx.principal.has("changes:read"):
        num = q.upper().removeprefix("CHG-")
        cond = ChangeRequest.title.ilike(like)
        if num.isdigit():
            cond = or_(cond, ChangeRequest.number == int(num))
        for c in ctx.db.scalars(select(ChangeRequest).where(ChangeRequest.tenant_id == t, cond).limit(5)):
            out.append(
                {
                    "type": "change",
                    "id": str(c.id),
                    "title": f"CHG-{c.number} {c.title}",
                    "subtitle": c.state,
                    "href": f"/changes/{c.id}",
                }
            )
    for m in ctx.db.scalars(
        select(IxpMember)
        .where(
            IxpMember.tenant_id == t,
            or_(IxpMember.name.ilike(like), cast(IxpMember.asn, String) == q.upper().removeprefix("AS")),
        )
        .limit(5)
    ):
        out.append(
            {
                "type": "ixp_member",
                "id": str(m.id),
                "title": f"AS{m.asn} {m.name}",
                "subtitle": "IXP member",
                "href": f"/ixp?asn={m.asn}",
            }
        )
    return out
