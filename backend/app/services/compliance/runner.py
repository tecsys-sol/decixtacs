"""Run compliance rules over the latest backup of every device and persist history."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utcnow
from app.models import (
    ComplianceResult,
    ComplianceRule,
    ComplianceRun,
    ConfigBackup,
    Device,
    DeviceComplianceScore,
    Tenant,
)
from app.services import metrics
from app.services.alerting import emit_event
from app.services.backup.engine import device_relpath, store_for
from app.services.compliance.engine import Rule, evaluate


def run_compliance(db: Session, tenant_id: uuid.UUID, device_ids: list[uuid.UUID] | None = None) -> ComplianceRun:
    run = ComplianceRun(tenant_id=tenant_id, started_at=utcnow())
    db.add(run)
    db.flush()
    rules_db = list(
        db.scalars(select(ComplianceRule).where(ComplianceRule.tenant_id == tenant_id, ComplianceRule.enabled))
    )
    q = (
        select(Device)
        .where(Device.tenant_id == tenant_id)
        .options(selectinload(Device.platform), selectinload(Device.site), selectinload(Device.groups))
    )
    if device_ids:
        q = q.where(Device.id.in_(device_ids))
    store = store_for(db, tenant_id)
    scores: list[float] = []
    for dev in db.scalars(q):
        backup = db.scalar(
            select(ConfigBackup)
            .where(ConfigBackup.device_id == dev.id, ConfigBackup.commit_sha.is_not(None))
            .order_by(ConfigBackup.collected_at.desc())
            .limit(1)
        )
        if backup is None:
            continue
        config = store.read(device_relpath(dev), backup.commit_sha) or ""
        group_ids = {g.id for g in dev.groups}
        applicable = [r for r in rules_db if r.device_group_id is None or r.device_group_id in group_ids]
        rules = [
            Rule(
                str(r.id),
                r.name,
                r.rule_type,
                r.pattern,
                r.severity,
                r.block_start,
                r.min_count,
                tuple(r.platforms or ()),
            )
            for r in applicable
        ]
        results, score = evaluate(rules, config, dev.platform.slug if dev.platform else None)
        sev = {str(r.id): r.severity for r in applicable}
        failed = [x for x in results if not x.passed]
        for x in results:
            db.add(
                ComplianceResult(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    device_id=dev.id,
                    rule_id=uuid.UUID(x.rule_id),
                    passed=x.passed,
                    detail=x.detail[:2000],
                    backup_id=backup.id,
                )
            )
            if not x.passed:
                metrics.COMPLIANCE_FAILURES.labels(severity=sev[x.rule_id]).inc()
        db.add(
            DeviceComplianceScore(
                tenant_id=tenant_id,
                run_id=run.id,
                device_id=dev.id,
                score=score,
                passed=len(results) - len(failed),
                failed=len(failed),
            )
        )
        scores.append(score)
        crit = [x for x in failed if sev[x.rule_id] in ("high", "critical")]
        if crit:
            emit_event(
                db,
                tenant_id,
                "compliance_failure",
                severity="high",
                title=f"{dev.hostname}: {len(crit)} high/critical compliance failure(s)",
                body="\n".join(x.detail for x in crit[:10]),
                device_id=dev.id,
                dedup_key=f"compliance:{dev.id}:{run.started_at.date()}",
            )
    run.devices_checked = len(scores)
    run.score = round(sum(scores) / len(scores), 2) if scores else None
    run.finished_at = utcnow()
    tenant = db.get(Tenant, tenant_id)
    if run.score is not None and tenant:
        metrics.COMPLIANCE_SCORE.labels(tenant=tenant.slug).set(run.score)
    db.flush()
    return run
