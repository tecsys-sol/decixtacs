"""Retention, metrics, env-bootstrapped integrations, SFOS collector, new endpoints, task retry."""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import respx
from prometheus_client import REGISTRY
from sqlalchemy import select

from app.cli import main
from app.core.config import get_settings
from app.db.base import utcnow
from app.models import (
    Alert,
    ChangeRequest,
    ConfigBackup,
    ConfigRestore,
    Device,
    Integration,
    LoginHistory,
    SessionRecording,
    User,
)
from tests.conftest import as_user
from tests.test_api_configs import CONFIGS, _backup, _device, fake_collector  # noqa: F401
from tests.test_api_tacacs import as_agent


def _gauge(tenant, vendor):
    return REGISTRY.get_sample_value("nom_devices", {"tenant": tenant, "vendor": vendor})


# --- 5. metrics -------------------------------------------------------------------------------


def test_device_gauge_follows_inventory(admin, db):
    platforms = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    d1 = admin.post(
        "/api/v1/devices", json={"hostname": "r1", "management_ip": "10.0.0.1", "platform_id": platforms["junos"]}
    ).json()
    admin.post(
        "/api/v1/devices", json={"hostname": "r2", "management_ip": "10.0.0.2", "platform_id": platforms["junos"]}
    )
    admin.post(
        "/api/v1/devices", json={"hostname": "sw1", "management_ip": "10.0.0.3", "platform_id": platforms["eos"]}
    )
    admin.post("/api/v1/devices", json={"hostname": "bare", "management_ip": "10.0.0.4"})
    assert _gauge("decix", "juniper") == 2 and _gauge("decix", "arista") == 1 and _gauge("decix", "unknown") == 1
    admin.delete(f"/api/v1/devices/{d1['id']}")
    assert _gauge("decix", "juniper") == 1
    # periodic task (beat) recomputes from scratch, dropping stale label sets
    from app.services import metrics
    from app.workers.tasks import refresh_metrics

    metrics.DEVICES.labels(tenant="gone", vendor="x").set(5)
    assert refresh_metrics.delay().get() == 3
    assert _gauge("gone", "x") is None and _gauge("decix", "arista") == 1


# --- 4. retention -----------------------------------------------------------------------------


def test_retention_backups_recordings_alerts(admin, db, tenant, tmp_path):
    from app.workers.tasks import apply_retention

    dev = admin.post("/api/v1/devices", json={"hostname": "r1", "management_ip": "10.0.0.1"}).json()
    did, old, new = uuid.UUID(dev["id"]), utcnow() - timedelta(days=400), utcnow() - timedelta(days=1)
    cr = admin.post("/api/v1/changes", json={"title": "x"}).json()

    def backup(status, when, changed=False, **kw):
        b = ConfigBackup(tenant_id=tenant.id, device_id=did, status=status, changed=changed, collected_at=when, **kw)
        db.add(b)
        db.flush()
        return b.id

    gone = [backup("unchanged", old, commit_sha="a" * 40), backup("failed", old, error="timeout")]
    kept = [
        backup("success", old, changed=True, commit_sha="b" * 40),
        backup("unchanged", old, change_request_id=uuid.UUID(cr["id"])),
        backup("unchanged", new),
        backup("failed", new),
    ]
    restored = backup("unchanged", old, commit_sha="c" * 40)
    db.add(ConfigRestore(tenant_id=tenant.id, device_id=did, backup_id=restored, dry_run=True, status="diffed"))
    kept.append(restored)
    files = []
    for when in (old, new):
        f = tmp_path / f"{uuid.uuid4()}.cast"
        f.write_text("{}")
        files.append(f)
        db.add(
            SessionRecording(
                tenant_id=tenant.id, username="u", device_address="10.0.0.1", started_at=when, storage_uri=f"file://{f}"
            )
        )
    db.add(Alert(tenant_id=tenant.id, event_type="backup_failed", severity="low", title="old", created_at=old))
    db.add(Alert(tenant_id=tenant.id, event_type="backup_failed", severity="low", title="new", created_at=new))
    db.add(LoginHistory(tenant_id=tenant.id, username="x", success=True, method="local", timestamp=old))
    db.commit()

    out = apply_retention.delay().get()
    assert out["config_backups"] == 2 and out["session_recordings"] == 1 and out["alerts"] == 1
    assert out["login_history"] == 1
    db.expire_all()
    left = set(db.scalars(select(ConfigBackup.id)))
    assert left == set(kept) and not (left & set(gone))
    assert not files[0].exists() and files[1].exists()
    assert [a.title for a in db.scalars(select(Alert))] == ["new"]
    assert db.scalar(select(SessionRecording.started_at)) > utcnow() - timedelta(days=2)


# --- 3. integrations from environment ----------------------------------------------------------


def test_integrations_from_env_cli(admin, db, monkeypatch, capsys):
    s = get_settings()
    main(["sync-integrations-from-env", "--tenant", "decix"])
    assert "nothing to do" in capsys.readouterr().out
    monkeypatch.setattr(s, "netbox_url", "https://netbox.example.net")
    monkeypatch.setattr(s, "netbox_token", "nb-token")
    monkeypatch.setattr(s, "ixpmanager_url", "https://ixp.example.net")
    monkeypatch.setattr(s, "ixpmanager_api_key", "ixp-key")
    main(["sync-integrations-from-env", "--tenant", "decix"])
    out = capsys.readouterr().out
    assert "netbox (from environment): created" in out and "ixpmanager (from environment): created" in out
    got = {i["kind"]: i for i in admin.get("/api/v1/integrations").json()}
    assert got["netbox"]["base_url"] == "https://netbox.example.net" and got["netbox"]["name"] == "netbox-env"
    assert got["ixpmanager"]["base_url"] == "https://ixp.example.net"
    from app.core.security import decrypt_secret

    db.expire_all()
    tokens = {i.kind: decrypt_secret(i.token_enc) for i in db.scalars(select(Integration))}
    assert tokens == {"netbox": "nb-token", "ixpmanager": "ixp-key"}

    # init on an existing tenant re-applies the env settings (idempotent)
    main(["init", "--slug", "decix", "--password", "x"])
    assert "netbox (from environment): unchanged" in capsys.readouterr().out
    monkeypatch.setattr(s, "netbox_token", "rotated")
    main(["sync-integrations-from-env", "--tenant", "decix"])
    assert "netbox (from environment): updated" in capsys.readouterr().out
    assert len(admin.get("/api/v1/integrations").json()) == 2
    assert admin.get("/api/v1/audit", params={"action": "integration.*"}).json()["total"] == 3


# --- 7. Sophos SFOS collector -------------------------------------------------------------------

SFOS_OK = """<?xml version="1.0" encoding="UTF-8"?>
<Response APIVersion="2000.1" IPS_CAT_VER="1">
  <Login><status>Authentication Successful</status></Login>
  <IPHost transactionid=""><Name>dns-1</Name><IPFamily>IPv4</IPFamily><HostType>IP</HostType><IPAddress>10.0.0.53</IPAddress></IPHost>
  <User transactionid=""><Username>ops</Username><Password>Sup3rS3cret</Password><EncryptedPassword>xyz==</EncryptedPassword></User>
  <VPNIPSecConnection transactionid=""><Name>hq</Name><PresharedKey>psk-123</PresharedKey></VPNIPSecConnection>
</Response>"""


@respx.mock
def test_sfos_collector_over_xml_api(admin):
    platforms = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    cred = admin.post("/api/v1/credentials", json={"name": "fw", "username": "api-backup", "password": "p<w>"}).json()
    fw = admin.post(
        "/api/v1/devices",
        json={
            "hostname": "xgs-fra1",
            "management_ip": "10.0.0.9",
            "platform_id": platforms["sfos"],
            "credential_id": cred["id"],
        },
    ).json()
    route = respx.post("https://10.0.0.9:4444/webconsole/APIController").mock(
        return_value=httpx.Response(200, text=SFOS_OK)
    )
    b = _backup(admin)[0]
    assert b["status"] == "success", b
    sent = route.calls[0].request.content.decode()
    assert "<Username>api-backup</Username><Password>p&lt;w&gt;</Password>" in sent
    assert "<Get><Zone/><Interface/>" in sent and "<FirewallRule/>" in sent
    cfg = admin.get(f"/api/v1/devices/{fw['id']}/config").text
    assert "<Login>" not in cfg and "transactionid" not in cfg and "IPS_CAT_VER" not in cfg
    assert "  <IPHost>\n    <Name>dns-1</Name>" in cfg  # pretty printed
    assert "Sup3rS3cret" not in cfg and "psk-123" not in cfg and "xyz==" not in cfg
    assert cfg.count("&lt;removed&gt;") == 3
    # unchanged on the next poll (volatile attributes stripped)
    assert _backup(admin)[0]["status"] == "unchanged"

    # per-device entity list + port; auth failure is a failed backup
    admin.patch(f"/api/v1/devices/{fw['id']}", json={"tags": ["fw"]})
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        d = s.get(Device, uuid.UUID(fw["id"]))
        d.custom_fields = {"api_port": 8443, "sfos_entities": ["IPHost"]}
        s.commit()
    bad = respx.post("https://10.0.0.9:8443/webconsole/APIController").mock(
        return_value=httpx.Response(
            200, text="<Response><Login><status>Authentication Failure</status></Login></Response>"
        )
    )
    b = _backup(admin)[0]
    assert b["status"] == "failed" and "Authentication Failure" in b["error"]
    assert "<Get><IPHost/></Get>" in bad.calls[0].request.content.decode()


def test_sfos_parser_rejects_entities():
    import pytest

    from app.services.backup.sfos import SfosError, parse_response

    with pytest.raises(SfosError):
        parse_response('<!DOCTYPE x [<!ENTITY a "b">]><Response/>')
    with pytest.raises(SfosError, match="529"):
        parse_response('<Response><Status code="529">Input request file is Invalid</Status></Response>')


# --- 6. per-tenant secret sanitising -------------------------------------------------------------


def test_tenant_can_keep_secrets_for_restorable_backups(admin, db, fake_collector, monkeypatch):  # noqa: F811
    from app.services import restore as restore_svc

    CONFIGS[3] = CONFIGS[1] + 'set system login user ops authentication encrypted-password "$6$real"\n'
    fake_collector["version"] = 3
    dev = _device(admin)
    _backup(admin)
    assert '"<removed>"' in admin.get(f"/api/v1/devices/{dev['id']}/config").text
    tid = admin.get("/api/v1/auth/me").json()["tenant_id"]
    assert (
        admin.patch(f"/api/v1/tenants/{tid}", json={"settings": {"backup_sanitize_secrets": False}}).status_code == 403
    )
    db.scalar(select(User).where(User.username == "admin")).is_superuser = True
    db.commit()
    r = admin.patch(f"/api/v1/tenants/{tid}", json={"settings": {"backup_sanitize_secrets": False}})
    assert r.status_code == 200 and r.json()["settings"] == {"backup_sanitize_secrets": False}
    b = _backup(admin)[0]
    assert b["status"] == "success" and "$6$real" in admin.get(f"/api/v1/devices/{dev['id']}/config").text
    monkeypatch.setattr(restore_svc, "scrapli_cfg_push", lambda t, cfg, dry: restore_svc.PushOutcome(True, "d", "ok"))
    r = admin.post(f"/api/v1/devices/{dev['id']}/restore", json={"backup_id": b["id"], "dry_run": True})
    assert r.status_code == 200 and r.json()["status"] == "diffed"
    # removing the override falls back to the global default (sanitise)
    r = admin.patch(f"/api/v1/tenants/{tid}", json={"settings": {"backup_sanitize_secrets": None}})
    assert r.json()["settings"] == {}
    assert admin.get("/api/v1/audit", params={"action": "tenant.update"}).json()["total"] == 2


# --- 8. new endpoints --------------------------------------------------------------------------


def test_session_detail_endpoint(admin):
    srv = admin.post("/api/v1/tacacs/servers", json={"name": "tac1", "address": "10.0.0.5"}).json()
    cast = (
        json.dumps({"version": 2, "width": 80, "height": 24}) + "\n" + json.dumps([0.2, "i", "show version\r"]) + "\n"
    )
    rec = (
        as_agent(admin, srv["agent_token"])
        .post(
            "/api/v1/sessions",
            files={"file": ("s.cast", cast.encode(), "application/x-asciicast")},
            data={"username": "alice", "device_address": "10.9.9.9"},
        )
        .json()
    )
    got = admin.get(f"/api/v1/sessions/{rec['id']}")
    assert got.status_code == 200 and got.json()["commands"] == [{"t": 0.2, "cmd": "show version"}]
    assert admin.get(f"/api/v1/sessions/{uuid.uuid4()}").status_code == 404
    assert admin.get("/api/v1/audit", params={"action": "session.*"}).json()["total"] == 0  # metadata not audited


def test_patch_tacacs_user_mapping(admin, client):
    u = admin.post("/api/v1/users", json={"username": "neteng", "password": "Str0ng-Passw0rd!"}).json()
    m = admin.post("/api/v1/tacacs/users", json={"user_id": u["id"], "password": "Tac-Passw0rd-2026"}).json()
    url = f"/api/v1/tacacs/users/{m['id']}"
    r = admin.patch(url, json={"enabled": False, "valid_until": "2027-01-31T00:00:00Z"})
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["valid_until"].startswith("2027-01-31")
    assert admin.patch(url, json={"password": "short"}).status_code == 422
    assert admin.patch(url, json={"auth_method": "radius"}).status_code == 422
    assert admin.patch(url, json={"enabled": None}).status_code == 422
    r = admin.patch(url, json={"auth_method": "ldap", "clear_password": True, "valid_until": None, "enabled": True})
    assert r.json() == {**r.json(), "auth_method": "ldap", "has_password": False, "valid_until": None, "enabled": True}
    r = admin.patch(url, json={"auth_method": "crypt", "password": "An0ther-Passw0rd!"})
    assert r.json()["has_password"] is True
    rendered = admin.get("/api/v1/tacacs/render").json()["content"]
    assert "neteng" in rendered
    events = admin.get("/api/v1/audit", params={"action": "tacacs.user.update"}).json()["items"]
    assert len(events) == 3 and events[0]["after"]["password_changed"] is True
    assert "An0ther" not in json.dumps(events)
    ro = admin.post("/api/v1/users", json={"username": "ro", "password": "Read-0nly-Passw0rd"}).json()
    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    admin.post("/api/v1/role-bindings", json={"role_id": roles["read-only"], "user_id": ro["id"]})
    assert as_user(client, "ro", "Read-0nly-Passw0rd").patch(url, json={"enabled": False}).status_code == 403


# --- 9. Git write race: retry config + adopting a commit from a failed attempt -----------------------


def test_backup_task_retry_config():
    from git.exc import GitCommandError

    from app.workers.tasks import backup_devices

    assert set(backup_devices.autoretry_for) == {GitCommandError, OSError}
    assert backup_devices.max_retries == 3 and backup_devices.retry_backoff and backup_devices.retry_jitter


def test_retry_adopts_commit_written_before_failure(admin, db, tenant, fake_collector):  # noqa: F811
    from app.services.backup.engine import device_relpath, store_for

    dev = _device(admin)
    b1 = _backup(admin)[0]
    # an earlier attempt committed version 2 to Git and then died before the DB commit
    d = db.get(Device, uuid.UUID(dev["id"]))
    store = store_for(db, tenant.id)
    sha = store.write(device_relpath(d), CONFIGS[2], author="shashank", author_email=None, subject="x", trailers={})
    fake_collector["version"] = 2
    b2 = _backup(admin)[0]
    assert b2["status"] == "success" and b2["changed"] and b2["commit_sha"] == sha and b2["author"] == "shashank"
    assert (b2["lines_added"], b2["lines_removed"]) == (1, 1)
    assert _backup(admin)[0]["status"] == "unchanged" and b1["commit_sha"] != sha


# --- 10. change request post-change snapshot -------------------------------------------------------


def test_change_request_pre_and_post_snapshots(admin, client, db, fake_collector):  # noqa: F811
    dev = _device(admin)
    _backup(admin)
    cr = admin.post("/api/v1/changes", json={"title": "Add VLAN", "device_ids": [dev["id"]]}).json()
    admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "submit"})
    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    mgr = admin.post("/api/v1/users", json={"username": "manager", "password": "Chg-Approver-2026"}).json()
    admin.post("/api/v1/role-bindings", json={"role_id": roles["change-manager"], "user_id": mgr["id"]})
    as_user(client, "manager", "Chg-Approver-2026").post(
        f"/api/v1/changes/{cr['id']}/transition", json={"transition": "approve"}
    )
    fake_collector["version"] = 2  # the engineer implements the change on the box
    r = admin.post(f"/api/v1/changes/{cr['id']}/transition", json={"transition": "implement"})
    assert r.status_code == 200 and r.json()["state"] == "implemented"
    assert len(r.json()["pre_backup_ids"]) == 1 and len(r.json()["post_backup_ids"]) == 1
    detail = admin.get(f"/api/v1/changes/{cr['id']}").json()
    by_id = {b["id"]: b for b in detail["backups"]}
    post = by_id[detail["change"]["post_backup_ids"][0]]
    pre = by_id[detail["change"]["pre_backup_ids"][0]]
    assert post["commit_sha"] != pre["commit_sha"] and post["reason"].startswith("CHG-1")
    db.expire_all()
    row = db.get(ConfigBackup, uuid.UUID(post["id"]))
    assert row.trigger == "change" and row.changed and db.get(ChangeRequest, uuid.UUID(cr["id"])).state == "implemented"
    # the post snapshot is not an "unplanned change"
    assert admin.get("/api/v1/alerts", params={"event_type": "config_drift"}).json()["total"] == 0
    assert Path(get_settings().backup_repo_root).exists()
