"""Charts are counted by the server over everything that matches, not from a capped list."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import (
    AuditEvent,
    ChangeRequest,
    ComplianceResult,
    ComplianceRule,
    ComplianceRun,
    ConfigBackup,
    Device,
    User,
)


def _devices(db, tenant, n=2):
    out = [Device(tenant_id=tenant.id, hostname=f"r{i}", management_ip=f"10.0.0.{i + 1}") for i in range(n)]
    db.add_all(out)
    db.flush()
    return out


def test_backup_activity_counts_every_backup(admin, db, tenant):
    r1, r2 = _devices(db, tenant)
    now = datetime.now(UTC) - timedelta(minutes=1)
    rows = []
    # 800 backups per device - well past the 500 the charts used to load
    for k in range(800):
        at = now - timedelta(hours=k * 0.5)  # ~16.6 days
        rows.append(ConfigBackup(tenant_id=tenant.id, device_id=r1.id, collected_at=at, status="unchanged"))
        rows.append(ConfigBackup(tenant_id=tenant.id, device_id=r2.id, collected_at=at, status="unchanged"))
    rows += [
        ConfigBackup(
            tenant_id=tenant.id,
            device_id=r1.id,
            collected_at=now - timedelta(hours=2),
            status="success",
            changed=True,
            lines_added=5,
            lines_removed=2,
        ),
        ConfigBackup(
            tenant_id=tenant.id,
            device_id=r1.id,
            collected_at=now - timedelta(days=3),
            status="success",
            changed=True,
            lines_added=1,
            lines_removed=1,
            author="manoj",
        ),
        ConfigBackup(tenant_id=tenant.id, device_id=r2.id, collected_at=now - timedelta(days=40), status="failed"),
        ConfigBackup(tenant_id=tenant.id, device_id=r2.id, collected_at=now - timedelta(hours=1), status="failed"),
    ]
    db.add_all(rows)
    db.commit()

    a = admin.get("/api/v1/backups/activity", params={"range": "7d", "tz": "Asia/Kolkata"}).json()
    assert a["outcomes"] == {"changed": 2, "unchanged": 1600, "failed": 1}  # the 40-day-old one is outside
    assert a["total"] == 1603
    assert len(a["days"]["starts"]) == 30 and sum(a["days"]["total"]) == 1603
    assert sum(a["days"]["ok"]) == 1602
    assert sum(a["days"]["changed"]) == 2
    assert sum(a["days"]["lines_added"]) == 6 and sum(a["days"]["lines_removed"]) == 3
    assert a["last_24h"] == {"changed": 1, "unplanned": 1}
    assert len(a["starts"]) == 28 and set(a["series"]) == {"Changed", "Unchanged", "Failed"}
    assert sum(a["series"]["Changed"]) == 2 and sum(a["series"]["Failed"]) == 1

    # the list's filters apply
    one = admin.get("/api/v1/backups/activity", params={"device_id": str(r1.id), "changed_only": True}).json()
    assert one["outcomes"] == {"changed": 2, "unchanged": 0, "failed": 0}
    assert admin.get("/api/v1/backups/activity", params={"author": "manoj"}).json()["total"] == 1
    assert admin.get("/api/v1/backups/activity", params={"tz": "Not/AZone"}).status_code == 422


def test_audit_activity_counts_every_event(admin, db, tenant):
    now = datetime.now(UTC) - timedelta(minutes=1)
    rows = [
        AuditEvent(
            tenant_id=tenant.id, actor_name="rancid", action="config.backup", timestamp=now - timedelta(minutes=k)
        )
        for k in range(1200)
    ]
    rows += [
        AuditEvent(tenant_id=tenant.id, actor_name="manoj", action=f"area{i}.do", timestamp=now - timedelta(hours=i))
        for i in range(6)
    ]
    db.add_all(rows)
    db.commit()
    a = admin.get("/api/v1/audit/activity", params={"actor": "rancid", "range": "24h"}).json()
    assert a["total"] == 1200 and a["actions"] == [{"name": "config.backup", "count": 1200}]
    assert a["in_range"] == 1200 and list(a["series"]) == ["config"]

    m = admin.get("/api/v1/audit/activity", params={"actor": "manoj", "range": "24h"}).json()
    assert m["total"] == 6 and len(m["areas"]) == 6
    assert len(m["series"]) == 5 and "Other" in m["series"] and sum(m["series"]["Other"]) == 2


def test_change_stats_counts_every_change(admin, db, tenant):
    user = db.query(User).filter(User.username == "admin").one()
    states = ["draft"] * 300 + ["closed"] * 400 + ["cancelled"] * 5
    db.add_all(
        ChangeRequest(
            tenant_id=tenant.id,
            number=i + 1,
            title=f"c{i}",
            state=s,
            risk="high" if i % 2 else "low",
            requested_by=user.id,
        )
        for i, s in enumerate(states)
    )
    db.commit()
    s = admin.get("/api/v1/changes/stats").json()
    assert s["total"] == 705
    assert s["states"] == {"draft": 300, "closed": 400, "cancelled": 5}
    assert sum(s["risks"].values()) == 705


def test_compliance_run_counts_every_failure(admin, db, tenant):
    devs = _devices(db, tenant, 60)
    rules = [
        ComplianceRule(tenant_id=tenant.id, name=f"rule{i}", rule_type="must_contain", pattern="x", severity=sev)
        for i, sev in enumerate(["critical", "high", "low"])
    ]
    run = ComplianceRun(tenant_id=tenant.id, id=uuid.uuid4())
    db.add_all([*rules, run])
    db.flush()
    # 60 devices x 3 rules x 30 results each = 5,400 failures - past the 5,000 the detail lists
    db.add_all(
        ComplianceResult(
            tenant_id=tenant.id, run_id=run.id, device_id=d.id, rule_id=r.id, passed=False, detail="missing"
        )
        for d in devs
        for r in rules
        for _ in range(30)
    )
    db.commit()
    d = admin.get(f"/api/v1/compliance/runs/{run.id}").json()
    assert len(d["failures"]) == 5000
    assert d["failures_total"] == 5400
    assert d["failures_by_severity"] == {"critical": 1800, "high": 1800, "low": 1800}
    assert d["failures_by_rule"] == {"rule0": 1800, "rule1": 1800, "rule2": 1800}
    assert d["rule_severity"]["rule0"] == "critical"
