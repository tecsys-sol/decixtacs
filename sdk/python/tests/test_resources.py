from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from networkops import ConflictError, NotFoundError, RateLimitError, ServerError, ValidationError
from tests.conftest import page

DEV = {"id": str(uuid.uuid4()), "hostname": "mx204-fra1", "management_ip": "192.0.2.1", "status": "active",
       "reachability": "up", "site": {"id": str(uuid.uuid4()), "name": "FRA1"},
       "platform": {"id": str(uuid.uuid4()), "slug": "junos", "name": "Juniper Junos"}, "vendor": None,
       "serial": None, "os_version": "23.4R1", "role": "edge", "backup_enabled": True, "ssh_port": 22,
       "tags": ["ix"], "netbox_id": 12, "credential_id": None, "last_backup_at": "2026-09-23T10:00:00Z",
       "last_backup_status": "success", "groups": [], "created_at": "2026-09-01T00:00:00+00:00",
       "some_future_field": 1}


def test_devices_iter_paginates_until_total(mock, client):
    devs = [{**DEV, "id": str(uuid.uuid4()), "hostname": f"r{i}"} for i in range(5)]
    route = mock.get("/devices").mock(side_effect=[
        httpx.Response(200, json=page(devs[:2], total=5, limit=2, offset=0)),
        httpx.Response(200, json=page(devs[2:4], total=5, limit=2, offset=2)),
        httpx.Response(200, json=page(devs[4:], total=5, limit=2, offset=4)),
    ])
    names = [d.hostname for d in client.devices.iter(vendor="juniper", page_size=2)]
    assert names == ["r0", "r1", "r2", "r3", "r4"]
    offsets = [r.request.url.params["offset"] for r in route.calls]
    assert offsets == ["0", "2", "4"]
    assert route.calls.last.request.url.params["vendor"] == "juniper"


def test_iter_max_items_and_empty_page(mock, client):
    mock.get("/devices").respond(json=page([DEV, DEV, DEV], total=100, limit=3))
    assert len(list(client.devices.iter(max_items=2))) == 2
    mock.get("/devices").respond(json=page([], total=0))
    assert list(client.devices.iter()) == []


def test_device_model_parsing(mock, client):
    mock.get(f"/devices/{DEV['id']}").respond(json=DEV)
    d = client.devices.get(DEV["id"])
    assert d.id == uuid.UUID(DEV["id"])
    assert d.platform.slug == "junos" and d.site.name == "FRA1"
    assert d.last_backup_at == datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    assert d.raw["some_future_field"] == 1  # unknown fields kept in raw, not an error


def test_device_create_update_delete(mock, client):
    create = mock.post("/devices").respond(201, json=DEV)
    patch = mock.patch(f"/devices/{DEV['id']}").respond(json={**DEV, "role": "core"})
    delete = mock.delete(f"/devices/{DEV['id']}").respond(204)
    site = uuid.uuid4()
    client.devices.create(hostname="mx204-fra1", management_ip="192.0.2.1", site_id=site, tags=["ix"])
    assert json.loads(create.calls.last.request.content)["site_id"] == str(site)
    assert client.devices.update(DEV["id"], role="core").role == "core"
    assert client.devices.delete(DEV["id"]) is None
    assert delete.called and patch.called


def test_backups_diff_config_and_restore(mock, client):
    dev = DEV["id"]
    mock.get(f"/devices/{dev}/config").respond(text="set system host-name mx204\n")
    diff = mock.get(f"/devices/{dev}/diff").respond(json={
        "old_rev": "HEAD~1", "new_rev": "HEAD", "unified": "--- a\n+++ b\n", "side_by_side": [], "inline": None,
        "added": 3, "removed": 1, "risk": {"score": 40, "level": "medium", "findings": [], "summary": ""}})
    restore = mock.post(f"/devices/{dev}/restore").respond(json={
        "id": str(uuid.uuid4()), "device_id": dev, "backup_id": str(uuid.uuid4()), "dry_run": True,
        "status": "diffed", "device_diff": "[edit]\n-  foo", "output": None, "pre_restore_backup_id": None,
        "created_at": "2026-09-23T10:00:00Z"})
    assert client.backups.config(dev, rev="abc123").startswith("set system")
    d = client.backups.diff(dev, "HEAD~1")
    assert (d.added, d.removed, d.risk["level"]) == (3, 1, "medium")
    assert diff.calls.last.request.url.params["old"] == "HEAD~1"
    assert diff.calls.last.request.url.params["include_inline"] == "false"
    r = client.backups.restore(dev, "b1")
    assert r.status == "diffed" and r.dry_run
    assert json.loads(restore.calls.last.request.content) == {"backup_id": "b1", "dry_run": True,
                                                              "confirm": False, "change_request_id": None}


def test_backups_run_sync_parses_models(mock, client):
    b = {"id": str(uuid.uuid4()), "device_id": DEV["id"], "collected_at": "2026-09-23T10:00:00Z",
         "status": "success", "changed": True, "commit_sha": "a" * 40, "trigger": "manual"}
    mock.post("/backups/run").respond(json={"backups": [b]})
    out = client.backups.run([DEV["id"]], reason="pre-maintenance", run_async=False)
    assert out["backups"][0].commit_sha == "a" * 40
    mock.post("/backups/run").respond(json={"task_id": "t-1"})
    assert client.backups.run()["task_id"] == "t-1"


def test_backups_list_filters(mock, client):
    route = mock.get("/backups").respond(json=page([]))
    client.backups.list(changed_only=True, since=datetime(2026, 9, 1, tzinfo=UTC), author="alice")
    p = route.calls.last.request.url.params
    assert p["changed_only"] == "true" and p["author"] == "alice"
    assert p["since"] == "2026-09-01T00:00:00+00:00"
    assert "status" not in p  # None values are not sent


def test_tacacs_render_and_deploy(mock, client):
    sid = str(uuid.uuid4())
    render = mock.get("/tacacs/render").respond(json={"sha256": "f" * 64, "warnings": ["mikrotik skipped"],
                                                      "content": 'key = "***"'})
    mock.post(f"/tacacs/servers/{sid}/deploy").respond(json={"id": str(uuid.uuid4()), "server_id": sid,
                                                             "version": 4, "sha256": "f" * 64,
                                                             "created_at": "2026-09-23T10:00:00Z"})
    r = client.tacacs.render(server_id=sid)
    assert r.warnings == ["mikrotik skipped"] and "***" in r.content
    assert render.calls.last.request.url.params["server_id"] == sid
    rev = client.tacacs.deploy(sid)
    assert rev.version == 4 and rev.server_id == uuid.UUID(sid)


def test_tacacs_create_server_returns_agent_token(mock, client):
    mock.post("/tacacs/servers").respond(201, json={
        "id": str(uuid.uuid4()), "name": "tac-fra", "address": "192.0.2.49", "port": 49, "enabled": True,
        "ldap_backend": False, "config_version": 0, "config_sha256": None, "last_deployed_at": None,
        "last_heartbeat_at": None, "agent_token": "nomagent_x"})
    assert client.tacacs.create_server(name="tac-fra", address="192.0.2.49").agent_token == "nomagent_x"


def test_accounting_search(mock, client):
    rec = {"id": str(uuid.uuid4()), "timestamp": "2026-09-23T10:01:02Z", "username": "alice",
           "device_address": "192.0.2.1", "command": "request system reboot", "result": "accounted",
           "record_type": "stop", "dangerous": "reboot"}
    route = mock.get("/accounting/commands").respond(json=page([rec]))
    p = client.accounting.search(user="alice", command="~^request system", start=datetime(2026, 9, 23, tzinfo=UTC))
    assert p.items[0].dangerous == "reboot" and p.total == 1 and not p.has_more
    params = route.calls.last.request.url.params
    assert params["command"] == "~^request system" and params["user"] == "alice"


def test_compliance(mock, client):
    run = {"id": str(uuid.uuid4()), "started_at": "2026-09-23T02:30:00Z", "finished_at": None,
           "devices_checked": 10, "score": 97.5}
    mock.get("/compliance/runs").respond(json=[run])
    mock.post("/compliance/run").respond(json=run)
    assert client.compliance.latest_score() == 97.5
    assert client.compliance.run().devices_checked == 10


def test_changes_workflow_and_errors(mock, client):
    cid = str(uuid.uuid4())
    chg = {"id": cid, "number": 42, "title": "Add IX VLAN", "state": "pending_approval", "risk": "medium",
           "device_ids": [DEV["id"]], "pre_backup_ids": [], "post_backup_ids": []}
    create = mock.post("/changes").respond(201, json={**chg, "state": "draft"})
    tr = mock.post(f"/changes/{cid}/transition").respond(json=chg)
    c = client.changes.create(title="Add IX VLAN", device_ids=[DEV["id"]],
                              scheduled_start=datetime(2026, 10, 1, 22, tzinfo=UTC))
    assert c.key == "CHG-42" and c.state == "draft"
    assert json.loads(create.calls.last.request.content)["scheduled_start"] == "2026-10-01T22:00:00+00:00"
    assert client.changes.submit(cid, "ready").state == "pending_approval"
    assert json.loads(tr.calls.last.request.content) == {"transition": "submit", "comment": "ready",
                                                         "take_backup": True}
    mock.post(f"/changes/{cid}/transition").respond(409, json={
        "detail": "four-eyes principle: requester cannot approve their own change"},
        headers={"X-Request-ID": "rid-1"})
    with pytest.raises(ConflictError) as e:
        client.changes.approve(cid)
    assert "four-eyes" in str(e.value) and e.value.request_id == "rid-1"


def test_audit_verify_and_iter(mock, client):
    mock.get("/audit/verify").respond(json={"intact": True, "events_verified": 12})
    ev = {"id": str(uuid.uuid4()), "timestamp": "2026-09-23T10:00:00Z", "actor_name": "alice",
          "action": "tacacs.deploy", "outcome": "success", "after": {"version": 3}}
    route = mock.get("/audit").respond(json=page([ev]))
    assert client.audit.verify()["intact"] is True
    events = list(client.audit.iter(action="tacacs.*"))
    assert events[0].after == {"version": 3}
    assert route.calls.last.request.url.params["action"] == "tacacs.*"


def test_error_mapping(mock, client):
    mock.get("/devices/x").respond(404, json={"detail": "device not found"})
    with pytest.raises(NotFoundError):
        client.devices.get("x")
    mock.post("/devices").respond(422, json={"detail": [{"loc": ["body", "hostname"], "msg": "required"}]})
    with pytest.raises(ValidationError) as e:
        client.devices.create(hostname="", management_ip="")
    assert isinstance(e.value.detail, list)


def test_retries_idempotent_requests_on_503_and_429(mock, client):
    route = mock.get("/devices").mock(side_effect=[
        httpx.Response(503), httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json=page([]))])
    assert client.devices.list().total == 0
    assert route.call_count == 3


def test_does_not_retry_post_on_503_but_raises(mock, client):
    route = mock.post("/compliance/run").respond(503, json={"detail": "down"})
    with pytest.raises(ServerError):
        client.compliance.run()
    assert route.call_count == 1


def test_rate_limit_error_after_retries(mock, client):
    mock.get("/devices").respond(429, json={"detail": "rate limit exceeded"}, headers={"Retry-After": "60"})
    with pytest.raises(RateLimitError) as e:
        client.devices.list()
    assert e.value.retry_after == 60.0


def test_transport_errors_are_retried_for_get(mock, client):
    route = mock.get("/audit/verify").mock(side_effect=[httpx.ConnectError("boom"),
                                                        httpx.Response(200, json={"intact": True})])
    assert client.audit.verify() == {"intact": True}
    assert route.call_count == 2
