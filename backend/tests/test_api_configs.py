import pytest

from app.services.backup import engine
from app.services.backup.collector import CollectResult

CONFIGS = {
    1: """set system host-name mx204-blr
set system ntp server 10.0.0.10
set system syslog host 10.0.0.20 any notice
set snmp community public authorization read-only
set protocols bgp group TRANSIT neighbor 10.0.0.2 peer-as 13335
set policy-options community IX members 65000:100
""",
}
CONFIGS[2] = (
    CONFIGS[1].replace("set protocols bgp group TRANSIT neighbor 10.0.0.2 peer-as 13335\n", "")
    + "set interfaces ae0 unit 446 vlan-id 446\n"
)


@pytest.fixture
def fake_collector(monkeypatch):
    state = {"version": 1, "fail": set()}

    def collect(targets, workers=50, timeout=60):
        return [
            CollectResult(t.device_id, False, error="connection timed out")
            if t.hostname in state["fail"]
            else CollectResult(t.device_id, True, config=CONFIGS[state["version"]], duration_ms=120)
            for t in targets
        ]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    return state


def _device(admin, name="mx204-blr", ip="10.0.0.1"):
    platforms = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    cred = admin.post("/api/v1/credentials", json={"name": f"c-{name}", "username": "backup", "password": "pw"}).json()
    site = admin.get("/api/v1/sites").json()
    site_id = (
        site[0]["id"] if site else admin.post("/api/v1/sites", json={"name": "Bangalore", "slug": "blr"}).json()["id"]
    )
    return admin.post(
        "/api/v1/devices",
        json={
            "hostname": name,
            "management_ip": ip,
            "site_id": site_id,
            "platform_id": platforms["junos"],
            "credential_id": cred["id"],
        },
    ).json()


def _backup(admin, **kw):
    r = admin.post("/api/v1/backups/run", json={"run_async": False, **kw})
    assert r.status_code == 200, r.text
    return r.json()["backups"]


def test_backup_diff_search_compliance(admin, fake_collector):
    dev = _device(admin)
    b1 = _backup(admin)[0]
    assert b1["status"] == "success" and b1["reason"] == "Initial backup" and b1["commit_sha"]
    assert _backup(admin)[0]["status"] == "unchanged"

    # an engineer changes the box; TACACS accounting tells us who
    from tests.test_api_tacacs import as_agent

    srv = admin.post("/api/v1/tacacs/servers", json={"name": "tac1", "address": "10.0.0.5"}).json()
    from datetime import UTC, datetime

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S +0000")
    as_agent(admin, srv["agent_token"]).post(
        "/api/v1/accounting/ingest",
        json={
            "lines": [
                f'{ts}\t10.0.0.1\tshashank\tssh\t192.0.2.10\tstop\tservice=junos-exec\tcmd=commit comment "Added new IX VLAN"'
            ]
        },
    )
    fake_collector["version"] = 2
    b3 = _backup(admin)[0]
    assert b3["status"] == "success" and b3["author"] == "shashank" and b3["reason"] == "Added new IX VLAN"
    assert (b3["lines_added"], b3["lines_removed"]) == (1, 1) and b3["risk_score"] >= 25

    hist = admin.get(f"/api/v1/devices/{dev['id']}/history").json()
    assert len(hist) == 2 and hist[0]["author"] == "shashank"
    assert "Reason: Added new IX VLAN" in hist[0]["message"]
    d = admin.get(
        f"/api/v1/devices/{dev['id']}/diff",
        params={"old": b1["commit_sha"], "new": b3["commit_sha"], "include_inline": True},
    ).json()
    assert "+set interfaces ae0 unit 446 vlan-id 446" in d["unified"]
    assert "-set protocols bgp group TRANSIT neighbor 10.0.0.2 peer-as 13335" in d["unified"]
    assert d["risk"]["findings"] and d["inline"]
    assert "vlan-id 446" in admin.get(f"/api/v1/devices/{dev['id']}/config").text
    assert "peer-as 13335" in admin.get(f"/api/v1/devices/{dev['id']}/config", params={"rev": b1["commit_sha"]}).text

    # config intelligence reflects the latest backup
    assert admin.get("/api/v1/config-search", params={"peer_as": 13335}).json() == []
    hits = admin.get("/api/v1/config-search", params={"community": "65000:100"}).json()
    assert [h["hostname"] for h in hits] == ["mx204-blr"]
    assert admin.get("/api/v1/config-search", params={"kind": "vlan", "key": "446"}).json()[0]["key"] == "446"

    # unplanned change raised a drift alert
    assert admin.get("/api/v1/alerts", params={"event_type": "config_drift"}).json()["total"] == 1

    # compliance: public SNMP community fails, score < 100, history kept
    run = admin.post("/api/v1/compliance/run").json()
    assert run["devices_checked"] == 1 and run["score"] < 100
    detail = admin.get(f"/api/v1/compliance/runs/{run['id']}").json()
    assert "SNMP community must not be public" in detail["failures_by_rule"]
    assert admin.get("/api/v1/alerts", params={"event_type": "compliance_failure"}).json()["total"] == 1
    r = admin.post("/api/v1/compliance/rules", json={"name": "x", "rule_type": "must_match", "pattern": "("})
    assert r.status_code == 422

    dash = admin.get("/api/v1/dashboard").json()
    assert dash["devices"]["total"] == 1 and dash["compliance"]["score"] == run["score"]
    assert dash["recent_changes"][0]["author"] == "shashank"


def test_backup_failure_alerts(admin, fake_collector):
    _device(admin)
    fake_collector["fail"].add("mx204-blr")
    b = _backup(admin)[0]
    assert b["status"] == "failed"
    dev = admin.get("/api/v1/devices").json()["items"][0]
    assert dev["reachability"] == "down" and dev["last_backup_status"] == "failed"
    types = {a["event_type"] for a in admin.get("/api/v1/alerts").json()["items"]}
    assert {"backup_failed", "device_unreachable"} <= types
    assert admin.get("/api/v1/devices", params={"backup_status": "failed"}).json()["total"] == 1


def test_golden_config_drift(admin, fake_collector):
    dev = _device(admin)
    r = admin.post(
        "/api/v1/golden-configs",
        json={
            "name": "ntp",
            "device_id": dev["id"],
            "content": "set system ntp server 10.0.0.10\nset system ntp server 10.0.0.11\n",
        },
    )
    assert r.status_code == 201
    _backup(admin)
    drift = admin.get("/api/v1/drift").json()
    assert drift["total"] == 1 and "10.0.0.11" in drift["items"][0]["diff"]


def test_change_workflow_and_restore_guard(admin, client, fake_collector, monkeypatch):
    dev = _device(admin)
    b1 = _backup(admin)[0]
    cr = admin.post("/api/v1/changes", json={"title": "Add VLAN 446", "device_ids": [dev["id"]]}).json()
    assert cr["number"] == 1 and cr["state"] == "draft"
    assert admin.post("/api/v1/changes", json={"title": "second"}).json()["number"] == 2
    assert admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "approve"}).status_code == 409
    assert (
        admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "submit"}).json()["state"]
        == "pending_approval"
    )
    # four eyes: requester cannot approve
    r = admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "approve"})
    assert r.status_code == 409 and "four-eyes" in r.text

    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    mgr = admin.post("/api/v1/users", json={"username": "manager", "password": "Chg-Approver-2026"}).json()
    admin.post("/api/v1/role-bindings", json={"role_id": roles["change-manager"], "user_id": mgr["id"]})
    from tests.conftest import as_user

    m = as_user(client, "manager", "Chg-Approver-2026")
    assert (
        m.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "approve", "comment": "ok"}).json()[
            "state"
        ]
        == "approved"
    )
    detail = admin.get(f"/api/v1/changes/{cr['id']}").json()
    assert len(detail["change"]["pre_backup_ids"]) == 1  # snapshot taken on approval (eager celery)
    assert detail["allowed_transitions"] == ["implement", "cancel"]

    # restore: dry-run allowed; real push needs confirm + approved change covering the device
    from app.services import restore as restore_svc

    calls = []
    monkeypatch.setattr(
        restore_svc,
        "scrapli_cfg_push",
        lambda t, cfg, dry: calls.append(dry) or restore_svc.PushOutcome(True, "[edit]\n- x", "ok"),
    )
    url = f"/api/v1/devices/{dev['id']}/restore"
    r = admin.post(url, json={"backup_id": b1["id"], "dry_run": True})
    assert r.status_code == 200 and r.json()["status"] == "diffed", r.text
    assert admin.post(url, json={"backup_id": b1["id"], "dry_run": False}).status_code == 422
    assert admin.post(url, json={"backup_id": b1["id"], "dry_run": False, "confirm": True}).status_code == 409
    r = admin.post(url, json={"backup_id": b1["id"], "dry_run": False, "confirm": True, "change_request_id": cr["id"]})
    assert r.status_code == 200 and r.json()["status"] == "pushed" and r.json()["pre_restore_backup_id"]
    assert calls == [True, False]
    assert (
        admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "implement"}).json()["state"]
        == "implemented"
    )
    assert (
        admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "close"}).json()["state"] == "closed"
    )
    actions = [a["action"] for a in admin.get("/api/v1/audit", params={"action": "change.*"}).json()["items"]]
    assert actions[:2] == ["change.close", "change.implement"]
    assert admin.get("/api/v1/audit", params={"action": "config.restore*"}).json()["total"] == 2


def test_restore_refuses_masked_secrets(admin, fake_collector):
    CONFIGS[3] = CONFIGS[1] + 'set system login user ops authentication encrypted-password "$6$real"\n'
    fake_collector["version"] = 3
    dev = _device(admin)
    b = _backup(admin)[0]
    r = admin.post(f"/api/v1/devices/{dev['id']}/restore", json={"backup_id": b["id"], "dry_run": True})
    assert r.status_code == 422 and "masked secrets" in r.text


def test_audit_chain_survives_retention(admin):
    from sqlalchemy import text

    from app.db.session import engine

    for i in range(3):
        admin.post("/api/v1/sites", json={"name": f"s{i}", "slug": f"s{i}"})
    with engine.begin() as c:  # simulate the oldest partition being dropped by retention
        c.execute(text("SET LOCAL nom.allow_audit_purge = 'on'"))
        c.execute(text("DELETE FROM audit_events WHERE timestamp = (SELECT min(timestamp) FROM audit_events)"))
    assert admin.get("/api/v1/audit/verify").json()["intact"]
