"""Configuration backup end to end: Celery worker -> Nornir/Netmiko over SSH to the local sshd
("linux" devices) -> sanitise -> per-tenant Git -> history, diff, author correlation with TACACS
accounting, unplanned-change and golden-config drift alerts, running-vs-backup drift, compliance."""

from __future__ import annotations

import pytest
from conftest import Api, read_device_config, tac_client, wait_until, write_device_config
from tacacs_plus.flags import TAC_PLUS_ACCT_FLAG_STOP


def run_backup(admin: Api, device_ids: list[str], reason: str | None = None) -> dict[str, dict]:
    """Trigger a backup through the worker and wait for one new row per device."""
    before = {d: {b["id"] for b in admin.get("/backups", params={"device_id": d})["items"]} for d in device_ids}
    job = admin.post("/backups/run", {"device_ids": device_ids, "reason": reason})
    assert job["task_id"]

    def done():
        out = {}
        for d in device_ids:
            new = [b for b in admin.get("/backups", params={"device_id": d})["items"] if b["id"] not in before[d]]
            if not new:
                return None
            out[d] = new[0]
        return out

    return wait_until(done, 90, interval=1, what="backup rows from the Celery worker")


@pytest.fixture(scope="module")
def devs(linux_devices: dict) -> dict:
    return linux_devices


def test_initial_backup(admin: Api, devs: dict):
    d1, d2 = devs["dev1"], devs["dev2"]
    rows = run_backup(admin, [d1["id"], d2["id"]], reason="E2E initial backup")
    for d in (d1, d2):
        b = rows[d["id"]]
        assert b["status"] == "success", b["error"]
        assert b["changed"] and b["commit_sha"] and b["trigger"] == "manual"
        assert b["reason"] == "E2E initial backup" and b["author"] == "admin"
        stored = admin.request("GET", f"/devices/{d['id']}/config", expect=200).text
        assert stored.strip() == read_device_config(d["ssh_user"]).strip()
        hist = admin.get(f"/devices/{d['id']}/history")
        assert len(hist) == 1 and hist[0]["sha"] == b["commit_sha"]
    dev = admin.get(f"/devices/{d1['id']}")
    assert dev["last_backup_status"] == "success" and dev["reachability"] == "up"


def test_unchanged_backup(admin: Api, devs: dict):
    d1 = devs["dev1"]
    b = run_backup(admin, [d1["id"]])[d1["id"]]
    assert b["status"] == "unchanged" and not b["changed"]
    assert len(admin.get(f"/devices/{d1['id']}/history")) == 1


def test_change_with_author_from_tacacs_accounting(admin: Api, devs: dict, tacacs_env: dict):
    d1 = devs["dev1"]
    user = tacacs_env["username"]
    # the engineer's config session on the device is accounted by tac_plus-ng (NAS 127.0.0.1)
    for cmd in (b"cmd=configure terminal", b"cmd=ntp server 192.0.2.124"):
        r = tac_client().account(
            user, TAC_PLUS_ACCT_FLAG_STOP, arguments=[b"task_id=9001", b"service=shell", b"priv-lvl=15", cmd],
            rem_addr="198.51.100.7", port="vty1",
        )  # fmt: skip
        assert r.valid
    wait_until(
        lambda: admin.get("/accounting/commands", params={"user": user, "command": "configure terminal"})["items"],
        30,
        what="config-mode command in accounting",
    )
    write_device_config(d1["ssh_user"], read_device_config(d1["ssh_user"]) + "ntp server 192.0.2.124\n")
    b = run_backup(admin, [d1["id"]])[d1["id"]]
    assert b["status"] == "success" and b["changed"]
    assert b["author"] == user, "author must be correlated from TACACS accounting"
    assert b["lines_added"] == 1 and b["lines_removed"] == 0
    assert b["reason"] == "Configuration change detected"
    hist = admin.get(f"/devices/{d1['id']}/history")
    assert len(hist) == 2 and hist[0]["author"] == user and hist[0]["sha"] == b["commit_sha"]
    diff = admin.get(f"/devices/{d1['id']}/diff", params={"old": hist[1]["sha"], "new": hist[0]["sha"]})
    assert "+ntp server 192.0.2.124" in diff["unified"] and diff["added"] == 1
    assert {"type": "added", "right": "ntp server 192.0.2.124"}.items() <= next(
        r for r in diff["side_by_side"] if r["type"] == "added"
    ).items()
    # a change nobody announced via a change request raises an "unplanned change" alert
    alerts = admin.get("/alerts", params={"event_type": "config_drift", "limit": 100})["items"]
    assert any(f"Unplanned config change on {d1['hostname']} by {user}" == a["title"] for a in alerts)


def test_golden_config_drift(admin: Api, devs: dict, suffix: str):
    d2 = devs["dev2"]
    admin.post(
        "/golden-configs",
        {
            "name": f"ntp-baseline-{suffix}",
            "device_id": d2["id"],
            "mode": "snippet",
            "content": "ntp server 192.0.2.123\n",
        },
    )
    # remove the required NTP server on the device, then back it up
    cfg = read_device_config(d2["ssh_user"]).replace("ntp server 192.0.2.123\n", "")
    write_device_config(d2["ssh_user"], cfg + "logging host 192.0.2.50\n")
    b = run_backup(admin, [d2["id"]])[d2["id"]]
    assert b["changed"] and b["lines_removed"] == 1 and b["lines_added"] == 1
    drift = admin.get("/drift", params={"device_id": d2["id"]})["items"]
    assert any(e["kind"] == "backup_vs_golden" and "ntp server 192.0.2.123" in e["diff"] for e in drift)
    alerts = admin.get("/alerts", params={"event_type": "config_drift", "limit": 100})["items"]
    assert any(f"{d2['hostname']} drifted from golden config 'ntp-baseline-{suffix}'" == a["title"] for a in alerts)


def test_running_vs_backup_drift_check(admin: Api, devs: dict):
    d1 = devs["dev1"]
    write_device_config(d1["ssh_user"], read_device_config(d1["ssh_user"]) + "snmp-server community e2e RO\n")
    r = admin.post(f"/devices/{d1['id']}/drift-check")
    assert r["drifted"] and "snmp-server community" in r["diff"]
    assert any(e["kind"] == "running_vs_backup" for e in admin.get("/drift", params={"device_id": d1["id"]})["items"])
    # the drift check does not commit
    assert len(admin.get(f"/devices/{d1['id']}/history")) == 2


def test_config_search_and_compliance(admin: Api, devs: dict, suffix: str):
    # linux configs are not parsed into the config index - the search simply finds nothing
    assert admin.get("/config-search", params={"text": "192.0.2.124"}) == []
    admin.post(
        "/compliance/rules",
        {
            "name": f"ntp-configured-{suffix}",
            "rule_type": "must_match",
            "pattern": r"^ntp server \S+",
            "platforms": ["linux"],
            "severity": "high",
        },
    )
    run = admin.post("/compliance/run")
    assert run["devices_checked"] >= 2 and run["score"] is not None
    detail = admin.get(f"/compliance/runs/{run['id']}")
    hosts = {d["hostname"]: d for d in detail["devices"]}
    assert devs["dev1"]["hostname"] in hosts and devs["dev2"]["hostname"] in hosts
    # dev2 lost its NTP server in test_golden_config_drift -> our rule fails there only
    failed = {(f["device"], f["rule"]) for f in detail["failures"]}
    assert (devs["dev2"]["hostname"], f"ntp-configured-{suffix}") in failed
    assert (devs["dev1"]["hostname"], f"ntp-configured-{suffix}") not in failed


def test_failed_backup_raises_alert(admin: Api, devs: dict, suffix: str):
    linux = next(p for p in admin.get("/platforms") if p["slug"] == "linux")
    cred = admin.post("/credentials", {"name": f"bad-{suffix}", "username": "nomdev1", "password": "wrong-password"})
    dev = admin.post(
        "/devices",
        {
            "hostname": f"e2e-badcred-{suffix}",
            "management_ip": "127.0.0.3",
            "ssh_port": devs["dev1"]["ssh_port"],
            "platform_id": linux["id"],
            "credential_id": cred["id"],
        },
    )
    try:
        b = run_backup(admin, [dev["id"]])[dev["id"]]
        assert b["status"] == "failed" and "Authentication" in (b["error"] or "")
        alerts = admin.get("/alerts", params={"event_type": "backup_failed", "limit": 100})["items"]
        assert any(a["title"] == f"Backup failed: {dev['hostname']}" for a in alerts)
    finally:
        admin.delete(f"/devices/{dev['id']}")
