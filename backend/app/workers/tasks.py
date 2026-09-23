"""Background jobs (Celery). Each task opens its own DB session and commits on success."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import delete, select, text

from app.core.config import get_settings
from app.db.base import aware, utcnow
from app.db.session import SessionLocal
from app.models import (
    Alert,
    ChangeRequest,
    CommandLog,
    Device,
    Integration,
    LoginHistory,
    ReportSchedule,
    Tenant,
)
from app.services import metrics
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
PARTITIONED = ("command_logs", "audit_events", "tacacs_auth_events")


@contextmanager
def session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.backup_devices")
def backup_devices(tenant_id: str, device_ids: list[str], trigger: str = "manual", reason: str | None = None,
                   change_request_id: str | None = None, requested_by: str | None = None,
                   phase: str | None = None) -> dict:
    from app.services.backup.engine import run_backups

    with session() as db:
        backups = run_backups(db, uuid.UUID(tenant_id), [uuid.UUID(d) for d in device_ids] or None, trigger=trigger,
                              reason=reason, change_request_id=uuid.UUID(change_request_id) if change_request_id else None,
                              requested_by=requested_by)
        if change_request_id and phase in ("pre", "post"):
            cr = db.get(ChangeRequest, uuid.UUID(change_request_id))
            ids = [str(b.id) for b in backups]
            if phase == "pre":
                cr.pre_backup_ids = [*cr.pre_backup_ids, *ids]
            else:
                cr.post_backup_ids = [*cr.post_backup_ids, *ids]
        return {"total": len(backups), "failed": sum(b.status == "failed" for b in backups),
                "changed": sum(b.changed for b in backups)}


@celery_app.task(name="app.workers.tasks.run_backup_schedule")
def run_backup_schedule(chunk_size: int = 250) -> int:
    """Fan out: one task per chunk of devices so 10k devices spread across the collect workers."""
    n = 0
    with session() as db:
        for tenant in db.scalars(select(Tenant).where(Tenant.is_active)):
            ids = [str(i) for i in db.scalars(select(Device.id).where(Device.tenant_id == tenant.id,
                                                                     Device.backup_enabled, Device.status == "active"))]
            for i in range(0, len(ids), chunk_size):
                backup_devices.delay(str(tenant.id), ids[i:i + chunk_size], "schedule")
                n += 1
    return n


def run_integration_sync(db, integration: Integration) -> dict:
    from app.services.integrations import ixpmanager, netbox

    try:
        if integration.kind == "netbox":
            return netbox.sync(db, integration)
        if integration.kind == "ixpmanager":
            return ixpmanager.sync_members(db, integration)
        if integration.kind == "birdseye":
            return ixpmanager.sync_route_server(db, integration)
        raise ValueError(f"unknown integration kind {integration.kind}")
    except Exception as exc:
        from app.services.alerting import emit_event

        db.rollback()
        integration = db.get(Integration, integration.id)
        integration.last_sync_at, integration.last_sync_status = utcnow(), "failed"
        integration.last_sync_detail = {"error": str(exc)[:500]}
        metrics.SYNC_RUNS.labels(kind=integration.kind, status="failed").inc()
        emit_event(db, integration.tenant_id, "sync_failed", severity="medium",
                   title=f"{integration.kind} sync '{integration.name}' failed", body=str(exc)[:2000],
                   dedup_key=f"sync:{integration.id}")
        db.commit()
        raise


@celery_app.task(name="app.workers.tasks.sync_integration")
def sync_integration(integration_id: str) -> dict:
    with session() as db:
        return run_integration_sync(db, db.get(Integration, uuid.UUID(integration_id)))


@celery_app.task(name="app.workers.tasks.sync_all_integrations")
def sync_all_integrations() -> int:
    with session() as db:
        ids = [str(i) for i in db.scalars(select(Integration.id).where(Integration.enabled))]
    for i in ids:
        sync_integration.delay(i)
    return len(ids)


@celery_app.task(name="app.workers.tasks.run_compliance_all")
def run_compliance_all() -> int:
    from app.services.compliance.runner import run_compliance

    with session() as db:
        tenants = list(db.scalars(select(Tenant.id).where(Tenant.is_active)))
    for t in tenants:
        with session() as db:
            run_compliance(db, t)
    return len(tenants)


@celery_app.task(name="app.workers.tasks.deliver_alert")
def deliver_alert(alert_id: str, channel_ids: list[str]) -> list[dict]:
    from app.services.alerting import deliver_now

    with session() as db:
        alert = db.get(Alert, uuid.UUID(alert_id))
        return deliver_now(db, alert, [uuid.UUID(c) for c in channel_ids])


@celery_app.task(name="app.workers.tasks.apply_retention")
def apply_retention() -> dict:
    """Drop whole monthly partitions on PostgreSQL (cheap); row-delete elsewhere."""
    s = get_settings()
    out = {}
    with session() as db:
        if db.bind.dialect.name == "postgresql":
            for table, days in (("command_logs", s.retention_command_logs_days),
                                ("audit_events", s.retention_audit_days),
                                ("tacacs_auth_events", s.retention_command_logs_days)):
                out[table] = db.execute(text("SELECT nom_drop_old_partitions(:t, :d)"), {"t": table, "d": days}).scalar()
        else:
            cutoff = utcnow() - timedelta(days=s.retention_command_logs_days)
            out["command_logs"] = db.execute(delete(CommandLog).where(CommandLog.timestamp < cutoff)).rowcount
        cutoff = utcnow() - timedelta(days=s.retention_login_history_days)
        out["login_history"] = db.execute(delete(LoginHistory).where(LoginHistory.timestamp < cutoff)).rowcount
    return out


@celery_app.task(name="app.workers.tasks.ensure_partitions")
def ensure_partitions(months_ahead: int = 3) -> None:
    with session() as db:
        if db.bind.dialect.name != "postgresql":
            return
        for table in PARTITIONED:
            db.execute(text("SELECT nom_ensure_partitions(:t, :m)"), {"t": table, "m": months_ahead})


@celery_app.task(name="app.workers.tasks.run_report_schedules")
def run_report_schedules() -> int:
    from app.services import reports

    import smtplib
    from email.message import EmailMessage

    s = get_settings()
    due_after = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}
    sent = 0
    with session() as db:
        for sch in db.scalars(select(ReportSchedule).where(ReportSchedule.enabled)):
            if sch.last_run_at and aware(sch.last_run_at) + due_after[sch.period] > utcnow():
                continue
            r = reports.build(db, sch.tenant_id, sch.report_type, sch.period)
            fn, mime = reports.RENDERERS[sch.fmt]
            msg = EmailMessage()
            msg["Subject"] = f"[NetworkOps] {r.title}"
            msg["From"] = s.smtp_from
            msg["To"] = ", ".join(sch.recipients)
            msg.set_content(f"{r.title}\n{r.start:%Y-%m-%d %H:%M} - {r.end:%Y-%m-%d %H:%M} UTC\n")
            maintype, subtype = mime.split("/", 1)
            msg.add_attachment(fn(r), maintype=maintype, subtype=subtype, filename=f"{sch.report_type}.{sch.fmt}")
            try:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                    if s.smtp_starttls:
                        smtp.starttls()
                    if s.smtp_username:
                        smtp.login(s.smtp_username, s.smtp_password)
                    smtp.send_message(msg)
                sch.last_run_at = utcnow()
                sent += 1
            except OSError:
                log.exception("report email failed for schedule %s", sch.id)
    return sent
