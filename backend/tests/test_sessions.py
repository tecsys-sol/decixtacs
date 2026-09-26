from datetime import UTC, datetime, timedelta

from app.models import CommandLog, TacacsAuthEvent
from tests.test_api_configs import CONFIGS, _backup, _device, fake_collector  # noqa: F401


def _cmd(db, tenant, user, cmd, at, port="pts/1", src="192.0.2.10", result="accounted"):
    db.add(
        CommandLog(
            tenant_id=tenant.id,
            username=user,
            device_address="10.0.0.1",
            command=cmd,
            timestamp=at,
            port=port,
            source_address=src,
            result=result,
        )
    )


def test_sessions_and_device_activity(admin, db, tenant, fake_collector):  # noqa: F811
    dev = _device(admin)
    _backup(admin)  # first backup - not a change
    now = datetime.now(UTC)
    t0 = now - timedelta(hours=2)
    db.add(
        TacacsAuthEvent(
            tenant_id=tenant.id,
            username="priya",
            device_address="10.0.0.1",
            source_address="192.0.2.10",
            kind="authen",
            result="pass",
            timestamp=t0 - timedelta(minutes=2),
        )
    )
    for i, c in enumerate(
        ["show configuration", "configure private", "set interfaces ae0 unit 446 vlan-id 446", "commit"]
    ):
        _cmd(db, tenant, "priya", c, t0 + timedelta(minutes=i))
    _cmd(db, tenant, "priya", "request system reboot", t0 + timedelta(minutes=5), result="denied")
    # same user, same line, 2 hours later: a new session
    _cmd(db, tenant, "priya", "show bgp summary", now - timedelta(minutes=5))
    # another user who only logged in; a failed login
    db.add(
        TacacsAuthEvent(
            tenant_id=tenant.id,
            username="arjun",
            device_address="10.0.0.1",
            source_address="192.0.2.11",
            kind="authen",
            result="pass",
            timestamp=now - timedelta(minutes=30),
        )
    )
    db.add(
        TacacsAuthEvent(
            tenant_id=tenant.id,
            username="mallory",
            device_address="10.0.0.1",
            source_address="198.51.100.9",
            kind="authen",
            result="fail",
            timestamp=now - timedelta(minutes=20),
        )
    )
    db.commit()
    fake_collector["version"] = 2
    _backup(admin)  # the change priya made

    r = admin.get("/api/v1/user-sessions", params={"days": 1}).json()
    assert r["summary"] == {
        "sessions": 3,
        "users": 2,
        "commands": 6,
        "config_sessions": 1,
        "denied": 1,
        "logins": 2,
        "failed_logins": 1,
    }
    by_start = sorted(r["items"], key=lambda s: s["start"])
    cfg = by_start[0]
    assert cfg["username"] == "priya" and cfg["commands"] == 5 and cfg["config_commands"] == 3 and cfg["denied"] == 1
    assert cfg["login_at"] is not None and cfg["device_name"] == "mx204-blr" and cfg["port"] == "pts/1"
    assert cfg["change"] and cfg["change"]["added"] == 1 and cfg["change"]["removed"] == 1
    assert by_start[1]["username"] == "arjun" and by_start[1]["commands"] == 0  # login only
    assert by_start[2]["commands"] == 1 and by_start[2]["change"] is None
    only = admin.get("/api/v1/user-sessions", params={"days": 1, "config_only": True}).json()
    assert only["total"] == 1
    assert admin.get("/api/v1/user-sessions", params={"user": "arjun"}).json()["total"] == 1

    a = admin.get(f"/api/v1/devices/{dev['id']}/activity", params={"days": 7}).json()
    assert a["summary"]["changes"] == 1 and a["summary"]["backups"] == 2 and a["summary"]["sessions"] == 3
    assert a["changes"][0]["added"] == 1 and len(a["logins"]) == 3
    assert {x["result"] for x in a["logins"]} == {"pass", "fail"}
    today = a["per_day"][-1]
    assert today["changes"] == 1 and today["backups"] == 2 and today["sessions"] >= 1
    assert CONFIGS[2]
