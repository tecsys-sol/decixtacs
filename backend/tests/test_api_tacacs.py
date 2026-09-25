def _setup(admin):
    grp = admin.post("/api/v1/groups", json={"name": "noc"}).json()
    dg = admin.post("/api/v1/device-groups", json={"name": "core-routers", "kind": "core-routers"}).json()
    platforms = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    dev = admin.post(
        "/api/v1/devices",
        json={
            "hostname": "mx204-blr",
            "management_ip": "10.0.0.1",
            "platform_id": platforms["junos"],
            "group_ids": [dg["id"]],
        },
    ).json()
    return grp, dg, dev


def test_tacacs_end_to_end(admin, client):
    grp, dg, dev = _setup(admin)
    user = admin.post(
        "/api/v1/users", json={"username": "shashank", "password": "Shash-Pass-2026!", "group_ids": [grp["id"]]}
    ).json()
    srv = admin.post("/api/v1/tacacs/servers", json={"name": "tac1", "address": "10.0.0.5"}).json()
    agent_token = srv["agent_token"]

    r = admin.post("/api/v1/tacacs/devices/import-inventory")
    assert r.status_code == 200 and [n["name"] for n in r.json()] == ["mx204-blr"]
    assert r.json()[0]["vendor"] == "juniper"
    pol = admin.post(
        "/api/v1/tacacs/policies",
        json={
            "name": "noc-ro",
            "group_id": grp["id"],
            "device_group_id": dg["id"],
            "privilege_level": 1,
            "junos_class": "remote-ro",
            "command_rules": [{"action": "permit", "pattern": "^show "}, {"action": "deny", "pattern": "^request "}],
        },
    )
    assert pol.status_code == 201, pol.text
    assert (
        admin.post(
            "/api/v1/tacacs/policies",
            json={"name": "bad", "group_id": grp["id"], "command_rules": [{"action": "permit", "pattern": "("}]},
        ).status_code
        == 422
    )
    # time windows must use a syntax tac_plus-ng accepts (it rejects e.g. "Mon-Fri 08:00-18:00")
    for tw, ok in (
        ("Mon-Fri 08:00-18:00", False),
        ("*/5 * * * *", False),
        ("Wk0800-1800", True),
        ("* 8-17 * * 1-5", True),
    ):
        r = admin.post("/api/v1/tacacs/policies", json={"name": f"tw-{tw}", "group_id": grp["id"], "time_window": tw})
        assert r.status_code == (201 if ok else 422), (tw, r.text)
        if ok:
            assert admin.delete(f"/api/v1/tacacs/policies/{r.json()['id']}").status_code == 204
    m = admin.post("/api/v1/tacacs/users", json={"user_id": user["id"], "password": "Tacacs-Pass-2026!"})
    assert m.status_code == 201 and m.json()["has_password"]

    preview = admin.get("/api/v1/tacacs/render").json()
    assert "device mx204-blr" in preview["content"] and 'key = "***"' in preview["content"]
    assert "user shashank" in preview["content"] and "member = noc" in preview["content"]
    assert "device.tag == core-routers" in preview["content"]

    # agent cannot fetch before a deploy
    agent = as_agent(client, agent_token)
    assert agent.get("/api/v1/tacacs/agent/config").status_code == 404
    rev = admin.post(f"/api/v1/tacacs/servers/{srv['id']}/deploy").json()
    assert rev["version"] == 1
    r = agent.get("/api/v1/tacacs/agent/config")
    assert r.status_code == 200 and "***" not in r.text and r.headers["ETag"] == f'"{rev["sha256"]}"'
    assert r.headers["X-Config-Sha256"] == rev["sha256"] and "no-transform" in r.headers["Cache-Control"]
    for inm in (rev["sha256"], f'"{rev["sha256"]}"', f'W/"{rev["sha256"]}-gzip"'):  # as rewritten by proxies
        assert agent.get("/api/v1/tacacs/agent/config", headers={"If-None-Match": inm}).status_code == 304
    # idempotent deploy
    assert admin.post(f"/api/v1/tacacs/servers/{srv['id']}/deploy").json()["version"] == 1
    # changing policy without deploying: agent refuses to serve an unapproved render
    admin.put(
        f"/api/v1/tacacs/policies/{pol.json()['id']}", json={**pol.json(), "privilege_level": 5, "command_rules": []}
    )
    assert agent.get("/api/v1/tacacs/agent/config").status_code == 409
    assert admin.post(f"/api/v1/tacacs/servers/{srv['id']}/deploy").json()["version"] == 2

    # accounting ingest + search
    lines = [
        "2026-09-23 10:01:02 +0000\t10.0.0.1\tshashank\tssh\t192.0.2.10\tstop\tservice=shell\tcmd=show bgp summary <cr>",
        "2026-09-23 10:02:02 +0000\t10.0.0.1\tshashank\tssh\t192.0.2.10\tstop\tservice=shell\tcmd=request system reboot",
        "2026-09-23 10:03:02 +0000\t10.0.0.1\tshashank\tssh\t192.0.2.10\tdeny\tservice=shell\tcmd=configure",
        "garbage",
    ]
    assert admin.post("/api/v1/accounting/ingest", json={"lines": lines}).status_code == 401
    stats = agent.post("/api/v1/accounting/ingest", json={"lines": lines}).json()
    assert stats == {"accounting": 2, "auth": 1, "skipped": 1}
    res = admin.get("/api/v1/accounting/commands", params={"user": "shashank"}).json()
    assert res["total"] == 3
    assert any(i["dangerous"] for i in res["items"]) and all(i["device_name"] == "mx204-blr" for i in res["items"])
    assert admin.get("/api/v1/accounting/commands", params={"command": "bgp"}).json()["total"] == 1
    assert admin.get("/api/v1/accounting/commands", params={"command": "~^req.*reboot$"}).json()["total"] == 1
    assert admin.get("/api/v1/accounting/commands", params={"result": "denied"}).json()["total"] == 1
    alerts = admin.get("/api/v1/alerts", params={"event_type": "unauthorized_command"}).json()
    assert alerts["total"] == 1
    # audit trail captured the policy lifecycle
    actions = {a["action"] for a in admin.get("/api/v1/audit", params={"action": "tacacs.*"}).json()["items"]}
    assert {"tacacs.policy.create", "tacacs.policy.update", "tacacs.deploy"} <= actions
    assert admin.get("/api/v1/audit/verify").json()["intact"]


def test_rotate_nas_key(admin):
    n = admin.post("/api/v1/tacacs/devices", json={"name": "fw1", "address": "10.9.9.9", "vendor": "fortinet"}).json()
    k1 = admin.post(f"/api/v1/tacacs/devices/{n['id']}/rotate-key").json()["key"]
    k2 = admin.post(f"/api/v1/tacacs/devices/{n['id']}/rotate-key").json()["key"]
    assert k1 != k2 and len(k1) > 20
    assert (
        admin.post("/api/v1/tacacs/devices", json={"name": "x", "address": "1.1.1.1", "vendor": "nope"}).status_code
        == 422
    )


def as_agent(client, token):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_deploy_all_and_agent_status(admin, client):
    a = admin.post("/api/v1/tacacs/servers", json={"name": "netservices-1", "address": "172.31.29.99"}).json()
    b = admin.post("/api/v1/tacacs/servers", json={"name": "netservices-2", "address": "172.31.1.21"}).json()
    admin.post("/api/v1/tacacs/servers", json={"name": "lab", "address": "10.9.9.9", "enabled": False})
    admin.post("/api/v1/tacacs/devices", json={"name": "fw1", "address": "10.9.9.1", "vendor": "fortinet"})
    out = admin.post("/api/v1/tacacs/servers/deploy-all").json()
    assert [d["name"] for d in out["deployed"]] == ["netservices-1", "netservices-2"]
    assert all(d["created"] and d["version"] == 1 for d in out["deployed"]) and out["skipped"] == ["lab"]
    # unchanged -> nothing new is published
    again = admin.post("/api/v1/tacacs/servers/deploy-all").json()
    assert not any(d["created"] for d in again["deployed"])

    sha = out["deployed"][0]["sha256"]
    agent = as_agent(client, a["agent_token"])
    assert agent.post("/api/v1/tacacs/agent/heartbeat", json={"running_sha256": sha, "status": "ok"}).status_code == 204
    agent_b = as_agent(client, b["agent_token"])
    agent_b.post(
        "/api/v1/tacacs/agent/heartbeat", json={"running_sha256": "0" * 64, "status": "error", "message": "-P failed"}
    )
    servers = {s["name"]: s for s in admin.get("/api/v1/tacacs/servers").json()}
    assert servers["netservices-1"]["running_sha256"] == servers["netservices-1"]["config_sha256"]
    assert (
        servers["netservices-2"]["agent_status"] == "error" and servers["netservices-2"]["agent_message"] == "-P failed"
    )
