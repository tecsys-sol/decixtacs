"""Module 16 - Prometheus metrics exported on ``/metrics``."""

from prometheus_client import Counter, Gauge, Histogram

USER_LOGINS = Counter("nom_user_logins_total", "Successful portal logins", ["method"])
LOGIN_FAILURES = Counter("nom_login_failures_total", "Failed logins", ["source"])
BACKUPS = Counter("nom_config_backups_total", "Configuration backup attempts", ["status", "platform"])
BACKUP_DURATION = Histogram(
    "nom_config_backup_duration_seconds",
    "Config collection duration",
    ["platform"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 60, 120),
)
COMPLIANCE_FAILURES = Counter("nom_compliance_failures_total", "Failed compliance checks", ["severity"])
COMPLIANCE_SCORE = Gauge("nom_compliance_score", "Latest tenant compliance score", ["tenant"])
TACACS_REQUESTS = Counter("nom_tacacs_requests_total", "TACACS records ingested", ["kind", "result"])
DEVICES = Gauge("nom_devices", "Devices in inventory", ["tenant", "vendor"])
DRIFT_EVENTS = Counter("nom_config_drift_total", "Configuration drift detections", ["kind"])
ALERTS = Counter("nom_alerts_total", "Alerts raised", ["event_type", "severity"])
SYNC_RUNS = Counter("nom_integration_sync_total", "Integration sync runs", ["kind", "status"])
HTTP_REQUESTS = Histogram(
    "nom_http_request_duration_seconds",
    "API latency",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def refresh_device_gauge(db) -> int:
    """Recompute ``nom_devices{tenant,vendor}`` from the inventory (all tenants, stale label sets
    removed). Called by the periodic ``refresh_metrics`` task and after inventory mutations."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import aliased

    from app.models import Device, Platform, Tenant, Vendor

    pv = aliased(Vendor)
    vendor = func.coalesce(Vendor.slug, pv.slug, "unknown")
    rows = db.execute(
        select(Tenant.slug, vendor, func.count(Device.id))
        .select_from(Device)
        .join(Tenant, Tenant.id == Device.tenant_id)
        .outerjoin(Vendor, Vendor.id == Device.vendor_id)
        .outerjoin(Platform, Platform.id == Device.platform_id)
        .outerjoin(pv, pv.id == Platform.vendor_id)
        .group_by(Tenant.slug, vendor)
    ).all()
    DEVICES.clear()
    for tenant, v, n in rows:
        DEVICES.labels(tenant=tenant, vendor=v).set(n)
    return len(rows)


def safe_refresh_device_gauge(db) -> None:
    """Best effort from request handlers: metrics must never fail an inventory mutation."""
    import logging

    try:
        refresh_device_gauge(db)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("could not refresh nom_devices gauge", exc_info=True)
