"""Modules 4, 5, 6, 11 + config intelligence search, drift and change-risk analysis."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import String, cast, select

from app.api.deps import Ctx, get_owned, require
from app.api.v1.common import ORM, Page, paginate
from app.api.v1.inventory import visible_devices_filter
from app.models import (
    ChangeRequest,
    ComplianceResult,
    ComplianceRule,
    ComplianceRun,
    ConfigBackup,
    ConfigIndexEntry,
    ConfigRestore,
    Device,
    DeviceComplianceScore,
    DeviceGroup,
    DriftEvent,
    GoldenConfig,
)
from app.services import audit
from app.services import diff as diffsvc
from app.services.backup.engine import build_target, device_relpath, run_backups, store_for
from app.services.compliance.engine import Rule, evaluate_rule
from app.services.risk import analyse_diff

router = APIRouter(tags=["configs"])


class BackupOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    collected_at: datetime
    status: str
    changed: bool
    commit_sha: str | None
    size_bytes: int | None
    lines_added: int
    lines_removed: int
    author: str | None
    reason: str | None
    trigger: str
    change_request_id: uuid.UUID | None
    error: str | None
    duration_ms: int | None
    risk_score: int | None


def _device(ctx: Ctx, device_id: uuid.UUID, permission: str = "configs:read") -> Device:
    d = get_owned(ctx, Device, device_id, "device")
    if not ctx.principal.can_on_device(permission, d):
        raise HTTPException(404, "device not found")
    return d


@router.get("/backups", response_model=Page[BackupOut])
def list_backups(
    device_id: uuid.UUID | None = None,
    status: str | None = None,
    changed_only: bool = False,
    author: str | None = None,
    since: datetime | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("configs:read")),
):
    stmt = (
        select(ConfigBackup).where(ConfigBackup.tenant_id == ctx.tenant_id).order_by(ConfigBackup.collected_at.desc())
    )
    visible = visible_devices_filter(ctx, select(Device.id).where(Device.tenant_id == ctx.tenant_id), "configs:read")
    stmt = stmt.where(ConfigBackup.device_id.in_(visible))
    if device_id:
        stmt = stmt.where(ConfigBackup.device_id == device_id)
    if status:
        stmt = stmt.where(ConfigBackup.status == status)
    if changed_only:
        stmt = stmt.where(ConfigBackup.changed)
    if author:
        stmt = stmt.where(ConfigBackup.author == author)
    if since:
        stmt = stmt.where(ConfigBackup.collected_at >= since)
    return paginate(ctx.db, stmt, BackupOut, limit, offset)


class BackupRequest(BaseModel):
    device_ids: list[uuid.UUID] = []
    reason: str | None = None
    change_request_id: uuid.UUID | None = None
    run_async: bool = True


@router.post("/backups/run")
def trigger_backup(body: BackupRequest, ctx: Ctx = Depends(require("configs:backup"))):
    for did in body.device_ids:
        _device(ctx, did, "configs:backup")
    if body.change_request_id:
        get_owned(ctx, ChangeRequest, body.change_request_id, "change request")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="config.backup_requested",
        actor=ctx.user,
        after={"devices": [str(d) for d in body.device_ids] or "all", "reason": body.reason},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    if body.run_async:
        from app.workers.tasks import backup_devices

        job = backup_devices.delay(
            str(ctx.tenant_id),
            [str(d) for d in body.device_ids],
            "manual",
            body.reason,
            str(body.change_request_id) if body.change_request_id else None,
            ctx.user.username,
        )
        return {"task_id": job.id}
    backups = run_backups(
        ctx.db,
        ctx.tenant_id,
        body.device_ids or None,
        trigger="manual",
        reason=body.reason,
        change_request_id=body.change_request_id,
        requested_by=ctx.user.username,
    )
    ctx.db.commit()
    return {"backups": [BackupOut.model_validate(b) for b in backups]}


@router.get("/devices/{device_id}/config", response_class=PlainTextResponse)
def device_config(device_id: uuid.UUID, rev: str = "HEAD", ctx: Ctx = Depends(require("configs:read"))):
    d = _device(ctx, device_id)
    content = store_for(ctx.db, ctx.tenant_id).read(device_relpath(d), rev)
    if content is None:
        raise HTTPException(404, "no configuration stored for this revision")
    return content


@router.get("/devices/{device_id}/history")
def device_history(device_id: uuid.UUID, limit: int = Query(100, le=1000), ctx: Ctx = Depends(require("configs:read"))):
    d = _device(ctx, device_id)
    return [c.__dict__ for c in store_for(ctx.db, ctx.tenant_id).history(device_relpath(d), limit)]


class DiffOut(BaseModel):
    old_rev: str
    new_rev: str
    unified: str
    side_by_side: list[dict]
    inline: list[dict] | None = None
    added: int
    removed: int
    risk: dict


@router.get("/devices/{device_id}/diff", response_model=DiffOut)
def device_diff(
    device_id: uuid.UUID,
    old: str,
    new: str = "HEAD",
    context: int = 3,
    include_inline: bool = False,
    ctx: Ctx = Depends(require("configs:read")),
):
    """Diff two Git revisions (commit sha, ``HEAD~1`` ...) of a device configuration."""
    d = _device(ctx, device_id)
    store = store_for(ctx.db, ctx.tenant_id)
    path = device_relpath(d)
    a, b = store.read(path, old), store.read(path, new)
    if a is None or b is None:
        raise HTTPException(404, "revision not found")
    uni = diffsvc.unified(a, b, f"{d.hostname}@{old[:10]}", f"{d.hostname}@{new[:10]}", context)
    st = diffsvc.stats(a, b)
    r = analyse_diff(uni)
    return DiffOut(
        old_rev=old,
        new_rev=new,
        unified=uni,
        side_by_side=diffsvc.side_by_side(a, b, context),
        inline=diffsvc.inline(a, b) if include_inline else None,
        added=st.added,
        removed=st.removed,
        risk={"score": r.score, "level": r.level, "findings": r.findings, "summary": r.summary},
    )


@router.delete("/backups/{backup_id}", status_code=204)
def delete_backup(backup_id: uuid.UUID, ctx: Ctx = Depends(require("configs:delete"))):
    """Deletes the backup record (Git history is immutable and kept for forensic purposes)."""
    b = get_owned(ctx, ConfigBackup, backup_id, "backup")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="config.delete",
        actor=ctx.user,
        target_type="config_backup",
        target_id=b.id,
        before={"device_id": str(b.device_id), "commit": b.commit_sha},
        source_ip=ctx.ip,
    )
    ctx.db.delete(b)
    ctx.db.commit()


# --- restore -----------------------------------------------------------------------------


class RestoreIn(BaseModel):
    backup_id: uuid.UUID
    dry_run: bool = True
    change_request_id: uuid.UUID | None = None
    confirm: bool = False


class RestoreOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    backup_id: uuid.UUID
    dry_run: bool
    status: str
    device_diff: str | None
    output: str | None
    pre_restore_backup_id: uuid.UUID | None
    created_at: datetime


@router.post("/devices/{device_id}/restore", response_model=RestoreOut)
def restore(device_id: uuid.UUID, body: RestoreIn, ctx: Ctx = Depends(require("configs:restore"))):
    """Select commit -> review diff (dry run) -> confirm -> push. Real pushes need ``confirm=true``
    and, when the tenant enforces it, an approved change request."""
    from app.services.restore import scrapli_cfg_push

    d = _device(ctx, device_id, "configs:restore")
    b = get_owned(ctx, ConfigBackup, body.backup_id, "backup")
    if b.device_id != d.id or not b.commit_sha:
        raise HTTPException(422, "backup does not belong to this device or has no stored config")
    if not body.dry_run:
        if not body.confirm:
            raise HTTPException(422, "set confirm=true to push configuration to the device")
        from app.models import Tenant

        tenant = ctx.db.get(Tenant, ctx.tenant_id)
        if (tenant.settings or {}).get("restore_requires_change", True):
            cr = (
                get_owned(ctx, ChangeRequest, body.change_request_id, "change request")
                if body.change_request_id
                else None
            )
            if cr is None or cr.state != "approved" or str(d.id) not in [str(x) for x in cr.device_ids]:
                raise HTTPException(409, "an approved change request covering this device is required")
    if not (d.platform and d.platform.supports_config_replace):
        raise HTTPException(422, "platform does not support atomic config replace")
    target = build_target(d)
    if target is None:
        raise HTTPException(422, "device has no credential/platform")
    config = store_for(ctx.db, ctx.tenant_id).read(device_relpath(d), b.commit_sha)
    if config and ("<removed>" in config or "&lt;removed&gt;" in config):
        # Backups taken with NOM_BACKUP_SANITIZE_SECRETS mask secrets; pushing them would overwrite
        # real keys/passwords on the device with the placeholder.
        raise HTTPException(
            422,
            "this backup has masked secrets and cannot be restored verbatim; "
            "disable secret sanitising for restorable backups or restore manually",
        )
    r = ConfigRestore(
        tenant_id=ctx.tenant_id,
        device_id=d.id,
        backup_id=b.id,
        requested_by=ctx.user.id,
        change_request_id=body.change_request_id,
        dry_run=body.dry_run,
    )
    if not body.dry_run:
        pre = run_backups(
            ctx.db,
            ctx.tenant_id,
            [d.id],
            trigger="change",
            reason="pre-restore snapshot",
            change_request_id=body.change_request_id,
            requested_by=ctx.user.username,
        )
        r.pre_restore_backup_id = pre[0].id if pre else None
    outcome = scrapli_cfg_push(target, config or "", body.dry_run)
    r.device_diff, r.output = outcome.device_diff, outcome.output
    r.status = ("diffed" if body.dry_run else "pushed") if outcome.ok else "failed"
    ctx.db.add(r)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="config.restore" + (".dry_run" if body.dry_run else ""),
        actor=ctx.user,
        target_type="device",
        target_id=d.id,
        target_name=d.hostname,
        after={"commit": b.commit_sha, "status": r.status},
        outcome="success" if outcome.ok else "failure",
        source_ip=ctx.ip,
    )
    if not body.dry_run and outcome.ok:
        run_backups(
            ctx.db,
            ctx.tenant_id,
            [d.id],
            trigger="change",
            reason=f"restored to {b.commit_sha[:10]}",
            change_request_id=body.change_request_id,
            requested_by=ctx.user.username,
        )
    ctx.db.commit()
    return r


# --- golden configs & drift ----------------------------------------------------------------


class GoldenIn(BaseModel):
    name: str
    device_id: uuid.UUID | None = None
    device_group_id: uuid.UUID | None = None
    mode: str = "snippet"
    content: str
    ignore_patterns: list[str] = []


class GoldenOut(GoldenIn, ORM):
    id: uuid.UUID
    updated_at: datetime


@router.get("/golden-configs", response_model=list[GoldenOut])
def list_golden(ctx: Ctx = Depends(require("configs:read"))):
    return ctx.db.scalars(select(GoldenConfig).where(GoldenConfig.tenant_id == ctx.tenant_id)).all()


@router.post("/golden-configs", response_model=GoldenOut, status_code=201)
def create_golden(body: GoldenIn, ctx: Ctx = Depends(require("compliance:write"))):
    if (body.device_id is None) == (body.device_group_id is None):
        raise HTTPException(422, "exactly one of device_id / device_group_id")
    if body.device_id:
        get_owned(ctx, Device, body.device_id, "device")
    if body.device_group_id:
        get_owned(ctx, DeviceGroup, body.device_group_id, "device group")
    g = GoldenConfig(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(g)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="golden_config.create",
        actor=ctx.user,
        target_type="golden_config",
        target_id=g.id,
        target_name=g.name,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return g


@router.delete("/golden-configs/{golden_id}", status_code=204)
def delete_golden(golden_id: uuid.UUID, ctx: Ctx = Depends(require("compliance:write"))):
    g = get_owned(ctx, GoldenConfig, golden_id, "golden config")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="golden_config.delete",
        actor=ctx.user,
        target_type="golden_config",
        target_id=g.id,
        target_name=g.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(g)
    ctx.db.commit()


class DriftOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    detected_at: datetime
    kind: str
    diff: str
    resolved: bool


@router.get("/drift", response_model=Page[DriftOut])
def list_drift(
    resolved: bool = False,
    device_id: uuid.UUID | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    ctx: Ctx = Depends(require("configs:read")),
):
    stmt = (
        select(DriftEvent)
        .where(DriftEvent.tenant_id == ctx.tenant_id, DriftEvent.resolved.is_(resolved))
        .order_by(DriftEvent.detected_at.desc())
    )
    if device_id:
        stmt = stmt.where(DriftEvent.device_id == device_id)
    return paginate(ctx.db, stmt, DriftOut, limit, offset)


@router.post("/devices/{device_id}/drift-check")
def drift_check(device_id: uuid.UUID, ctx: Ctx = Depends(require("configs:backup"))):
    """Collect the running config now and compare it with the last backup (without committing)."""
    from app.services.backup import engine
    from app.services.backup.sanitize import prepare
    from app.services.drift import compare_running

    d = _device(ctx, device_id, "configs:backup")
    target = build_target(d)
    if target is None:
        raise HTTPException(422, "device has no credential/platform")
    res = engine.default_collect([target])[0]
    if not res.ok:
        raise HTTPException(502, f"collection failed: {res.error}")
    running = prepare(res.config, d.platform.slug, engine.sanitize_for(ctx.db, ctx.tenant_id))
    last = store_for(ctx.db, ctx.tenant_id).read(device_relpath(d)) or ""
    r = compare_running(running, last)
    if r.drifted:
        ctx.db.add(DriftEvent(tenant_id=ctx.tenant_id, device_id=d.id, kind="running_vs_backup", diff=r.diff))
        ctx.db.commit()
    return {"drifted": r.drifted, "diff": r.diff}


# --- config intelligence search ---------------------------------------------------------------


class IndexOut(ORM):
    device_id: uuid.UUID
    hostname: str | None = None
    kind: str
    key: str
    attributes: dict


@router.get("/config-search", response_model=list[IndexOut])
def config_search(
    kind: str | None = Query(
        None,
        description="bgp_neighbor|bgp_group|community|community_value|prefix_list|"
        "firewall_filter|policy|interface|vlan|routing_instance",
    ),
    key: str | None = Query(None, description="exact key, or prefix with trailing *"),
    peer_as: int | None = Query(None, description="BGP neighbours with this ASN"),
    community: str | None = Query(None, description="devices using this community value, e.g. 65000:100"),
    text: str | None = Query(None, description="free text over key and attributes"),
    limit: int = Query(200, le=2000),
    ctx: Ctx = Depends(require("configs:read")),
):
    """Examples: ``?community=65000:100``, ``?peer_as=13335``, ``?kind=prefix_list&key=XYZ``."""
    stmt = (
        select(ConfigIndexEntry, Device.hostname)
        .join(Device, Device.id == ConfigIndexEntry.device_id)
        .where(ConfigIndexEntry.tenant_id == ctx.tenant_id)
    )
    visible = visible_devices_filter(ctx, select(Device.id).where(Device.tenant_id == ctx.tenant_id), "configs:read")
    stmt = stmt.where(ConfigIndexEntry.device_id.in_(visible))
    if community:
        stmt = stmt.where(ConfigIndexEntry.kind == "community_value", ConfigIndexEntry.key == community)
    if peer_as is not None:
        kind = kind or "bgp_neighbor"
        stmt = stmt.where(ConfigIndexEntry.kind == kind)
    elif kind:
        stmt = stmt.where(ConfigIndexEntry.kind == kind)
    if key:
        stmt = stmt.where(
            ConfigIndexEntry.key.like(key[:-1] + "%") if key.endswith("*") else ConfigIndexEntry.key == key
        )
    if text:
        stmt = stmt.where(
            ConfigIndexEntry.key.ilike(f"%{text}%") | cast(ConfigIndexEntry.attributes, String).ilike(f"%{text}%")
        )
    out = []
    for entry, hostname in ctx.db.execute(stmt.limit(limit if peer_as is None else limit * 10)):
        if peer_as is not None and entry.attributes.get("peer_as") != peer_as:
            continue
        o = IndexOut.model_validate(entry)
        o.hostname = hostname
        out.append(o)
        if len(out) >= limit:
            break
    return out


class AnalyseIn(BaseModel):
    diff: str


@router.post("/analyse-diff")
def analyse(body: AnalyseIn, ctx: Ctx = Depends(require("configs:read"))):
    r = analyse_diff(body.diff)
    return {"score": r.score, "level": r.level, "findings": r.findings, "summary": r.summary}


# --- compliance ---------------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str
    description: str | None = None
    rule_type: str
    pattern: str
    block_start: str | None = None
    min_count: int = 1
    platforms: list[str] = []
    device_group_id: uuid.UUID | None = None
    severity: str = "medium"
    remediation: str | None = None
    enabled: bool = True


class RuleOut(RuleIn, ORM):
    id: uuid.UUID


@router.get("/compliance/rules", response_model=list[RuleOut])
def list_rules(ctx: Ctx = Depends(require("compliance:read"))):
    return ctx.db.scalars(
        select(ComplianceRule).where(ComplianceRule.tenant_id == ctx.tenant_id).order_by(ComplianceRule.name)
    ).all()


def _validate_rule(body: RuleIn) -> None:
    if body.rule_type not in ("must_match", "must_not_match", "count_at_least", "block_must_match"):
        raise HTTPException(422, "invalid rule_type")
    if body.severity not in ("low", "medium", "high", "critical"):
        raise HTTPException(422, "invalid severity")
    res = evaluate_rule(Rule("x", body.name, body.rule_type, body.pattern, body.severity, body.block_start), "")
    if res.detail.startswith("invalid pattern"):
        raise HTTPException(422, res.detail)


@router.post("/compliance/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, ctx: Ctx = Depends(require("compliance:write"))):
    _validate_rule(body)
    r = ComplianceRule(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="compliance.rule.create",
        actor=ctx.user,
        target_type="compliance_rule",
        target_id=r.id,
        target_name=r.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return r


@router.put("/compliance/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleIn, ctx: Ctx = Depends(require("compliance:write"))):
    _validate_rule(body)
    r = get_owned(ctx, ComplianceRule, rule_id, "rule")
    before = RuleOut.model_validate(r).model_dump(mode="json")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="compliance.rule.update",
        actor=ctx.user,
        target_type="compliance_rule",
        target_id=r.id,
        target_name=r.name,
        before=before,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return r


@router.delete("/compliance/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, ctx: Ctx = Depends(require("compliance:write"))):
    r = get_owned(ctx, ComplianceRule, rule_id, "rule")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="compliance.rule.delete",
        actor=ctx.user,
        target_type="compliance_rule",
        target_id=r.id,
        target_name=r.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(r)
    ctx.db.commit()


class RunOut(ORM):
    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    devices_checked: int
    score: float | None


@router.post("/compliance/run", response_model=RunOut)
def run_now(ctx: Ctx = Depends(require("compliance:write"))):
    from app.services.compliance.runner import run_compliance

    run = run_compliance(ctx.db, ctx.tenant_id)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="compliance.run",
        actor=ctx.user,
        after={"score": run.score, "devices": run.devices_checked},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return run


@router.get("/compliance/runs", response_model=list[RunOut])
def list_runs(limit: int = Query(30, le=365), ctx: Ctx = Depends(require("compliance:read"))):
    return ctx.db.scalars(
        select(ComplianceRun)
        .where(ComplianceRun.tenant_id == ctx.tenant_id)
        .order_by(ComplianceRun.started_at.desc())
        .limit(limit)
    ).all()


@router.get("/compliance/runs/{run_id}")
def run_detail(run_id: uuid.UUID, ctx: Ctx = Depends(require("compliance:read"))):
    run = get_owned(ctx, ComplianceRun, run_id, "run")
    scores = ctx.db.execute(
        select(DeviceComplianceScore, Device.hostname)
        .join(Device, Device.id == DeviceComplianceScore.device_id)
        .where(DeviceComplianceScore.run_id == run.id)
        .order_by(DeviceComplianceScore.score)
    ).all()
    failures = ctx.db.execute(
        select(ComplianceResult, ComplianceRule.name, ComplianceRule.severity, Device.hostname)
        .join(ComplianceRule, ComplianceRule.id == ComplianceResult.rule_id)
        .join(Device, Device.id == ComplianceResult.device_id)
        .where(ComplianceResult.run_id == run.id, ComplianceResult.passed.is_(False))
        .limit(5000)
    ).all()
    by_rule: dict[str, int] = {}
    for _, name, _, _ in failures:
        by_rule[name] = by_rule.get(name, 0) + 1
    return {
        "run": RunOut.model_validate(run),
        "devices": [
            {"device_id": str(s.device_id), "hostname": h, "score": s.score, "passed": s.passed, "failed": s.failed}
            for s, h in scores
        ],
        "failures": [{"device": h, "rule": n, "severity": sev, "detail": r.detail} for r, n, sev, h in failures],
        "failures_by_rule": by_rule,
    }
