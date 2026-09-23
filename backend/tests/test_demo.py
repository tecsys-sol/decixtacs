from datetime import datetime, timedelta

import pytest

from app.cli import main


def test_seed_demo_populates_every_dashboard_section(admin, capsys):
    main(["seed-demo", "--tenant", "decix"])
    assert "demo data: devices=13" in capsys.readouterr().out

    dash = admin.get("/api/v1/dashboard").json()
    assert dash["devices"]["total"] == 13
    assert {v["name"] for v in dash["devices"]["by_vendor"]} >= {"Juniper Networks", "Arista Networks", "Fortinet"}
    assert len(dash["devices"]["by_site"]) == 4 and dash["devices"]["by_reachability"]["down"] == 1
    assert dash["backups"]["last_24h"] >= 13 and dash["backups"]["failures_24h"] == 1
    assert dash["backups"]["devices_failing"] == 1
    assert dash["compliance"]["score"] is not None and len(dash["compliance"]["trend"]) >= 5
    assert dash["tacacs"]["accounting_24h"] > 0 and dash["tacacs"]["auth_24h"]["fail"] >= 6
    assert dash["top_users"] and dash["top_devices"] and dash["recent_audit"]
    assert len(dash["recent_changes"]) == 10 and any(c["author"] == "alice" for c in dash["recent_changes"])
    assert dash["open_changes"] == 2 and dash["open_alerts"] > 0

    # the rest of the UI has data too
    changes = admin.get("/api/v1/changes").json()
    assert {c["state"] for c in changes["items"]} == {
        "closed",
        "implemented",
        "approved",
        "pending_approval",
        "draft",
        "rejected",
    }
    closed = next(c for c in changes["items"] if c["state"] == "closed")
    assert len(closed["pre_backup_ids"]) == 1 and len(closed["post_backup_ids"]) == 1
    dev = next(
        d
        for d in admin.get("/api/v1/devices", params={"limit": 50}).json()["items"]
        if d["hostname"] == "7280r3-fra1-peer1"
    )
    hist = admin.get(f"/api/v1/devices/{dev['id']}/history").json()
    assert len(hist) >= 2 and "CHG-1" in "".join(h["message"] for h in hist)
    span = datetime.fromisoformat(hist[0]["timestamp"]) - datetime.fromisoformat(hist[-1]["timestamp"])
    assert span > timedelta(days=7)  # back-dated Git history
    assert admin.get("/api/v1/ixp/members").json() and admin.get("/api/v1/ixp/route-server-clients").json()
    assert admin.get("/api/v1/sessions").json()["total"] == 2
    assert len(admin.get("/api/v1/tacacs/users").json()) == 3 and admin.get("/api/v1/tacacs/policies").json()
    assert admin.get("/api/v1/alerts", params={"event_type": "unauthorized_command"}).json()["total"] == 1
    assert admin.get("/api/v1/config-search", params={"community": "65000:100"}).json()
    assert admin.get("/api/v1/audit/verify").json()["intact"]

    # refuses to seed twice, --force wipes and re-seeds deterministically
    serials = sorted(d["serial"] for d in admin.get("/api/v1/devices", params={"limit": 50}).json()["items"])
    with pytest.raises(SystemExit, match="already has 13 devices"):
        main(["seed-demo", "--tenant", "decix"])
    main(["seed-demo", "--tenant", "decix", "--force"])
    assert admin.get("/api/v1/devices").json()["total"] == 13
    assert admin.get("/api/v1/changes").json()["total"] == 6
    assert serials == sorted(d["serial"] for d in admin.get("/api/v1/devices", params={"limit": 50}).json()["items"])
