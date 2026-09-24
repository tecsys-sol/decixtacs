"""TACACS+ end to end: platform objects -> render -> deploy -> nom-tacacs-agent pulls, validates
(``tac_plus-ng -P``), installs and reloads -> real TACACS+ client traffic against tac_plus-ng ->
the agent ships the log lines -> accounting, auth events and alerts in the API."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from conftest import STACK, Api, tac_client, wait_until
from tacacs_plus.flags import (
    TAC_PLUS_ACCT_FLAG_START,
    TAC_PLUS_ACCT_FLAG_STOP,
    TAC_PLUS_AUTHEN_TYPE_PAP,
    TAC_PLUS_AUTHOR_STATUS_FAIL,
    TAC_PLUS_AUTHOR_STATUS_PASS_ADD,
)


def _shell(cmd: str) -> list[bytes]:
    words = cmd.split()
    return [b"service=shell", f"cmd={words[0]}".encode(), *[f"cmd-arg={w}".encode() for w in words[1:]],
            b"cmd-arg=<cr>"]  # fmt: skip


def test_agent_installed_deployed_revision(admin: Api, tacacs_env: dict):
    server_id = STACK["tacacs"]["server_id"]
    revs = admin.get(f"/tacacs/servers/{server_id}/revisions")
    assert revs[0]["sha256"] == tacacs_env["revision"]["sha256"]
    live = Path(STACK["tacacs"]["config_path"]).read_text()
    # the live file carries the real key; the stored revision / preview are redacted
    assert f"device e2e-local-{tacacs_env['nas']['name'].rsplit('-', 1)[1]}" in live
    assert 'key = "e2e-nas-secret-' in live
    preview = admin.get("/tacacs/render", params={"server_id": server_id})
    assert preview["sha256"] == tacacs_env["revision"]["sha256"]
    assert 'key = "***"' in preview["content"] and "e2e-nas-secret" not in preview["content"]
    assert f"tag = {tacacs_env['device_group']['name']}" in live
    server = next(s for s in admin.get("/tacacs/servers") if s["id"] == server_id)
    assert server["last_heartbeat_at"] is not None


def test_agent_config_endpoint_conditional_get(tacacs_env: dict, agent_http: httpx.Client):
    sha = tacacs_env["revision"]["sha256"]
    r = agent_http.get("/tacacs/agent/config")
    assert r.status_code == 200 and r.headers["etag"] == f'"{sha}"' and r.headers["x-config-sha256"] == sha
    assert agent_http.get("/tacacs/agent/config", headers={"If-None-Match": sha}).status_code == 304
    assert httpx.get(STACK["api_url"] + "/api/v1/tacacs/agent/config",
                     headers={"Authorization": "Bearer nomagent_wrong"}).status_code == 401  # fmt: skip


def test_authentication_ascii_and_pap(tacacs_env: dict):
    u, pw = tacacs_env["username"], tacacs_env["password"]
    assert tac_client().authenticate(u, pw, rem_addr="198.51.100.7", port="vty0").valid
    assert not tac_client().authenticate(u, pw + "x", rem_addr="198.51.100.7", port="vty0").valid
    assert tac_client().authenticate(u, pw, authen_type=TAC_PLUS_AUTHEN_TYPE_PAP).valid
    assert not tac_client().authenticate("no-such-user", "whatever").valid


def test_authorization_follows_policy(tacacs_env: dict):
    u = tacacs_env["username"]
    exec_ = tac_client().authorize(u, arguments=[b"service=shell", b"cmd="])
    assert exec_.valid and exec_.status == TAC_PLUS_AUTHOR_STATUS_PASS_ADD
    assert b"priv-lvl=1" in exec_.arguments
    assert tac_client().authorize(u, arguments=_shell("show version")).valid
    assert tac_client().authorize(u, arguments=_shell("ping 192.0.2.1")).valid
    denied = tac_client().authorize(u, arguments=_shell("show running-config"))
    assert not denied.valid and denied.status == TAC_PLUS_AUTHOR_STATUS_FAIL
    assert not tac_client().authorize(u, arguments=_shell("configure terminal")).valid  # default deny
    # a user without a mapping gets nothing
    assert not tac_client().authorize("no-such-user", arguments=_shell("show version")).valid


def test_accounting_start_stop(tacacs_env: dict):
    u = tacacs_env["username"]
    for flag in (TAC_PLUS_ACCT_FLAG_START, TAC_PLUS_ACCT_FLAG_STOP):
        r = tac_client().account(
            u, flag, arguments=[b"task_id=4711", b"service=shell", b"priv-lvl=1", b"cmd=show interfaces brief <cr>"],
            rem_addr="198.51.100.7", port="vty0",
        )  # fmt: skip
        assert r.valid


def _commands(admin: Api, **params) -> list[dict]:
    return admin.get("/accounting/commands", params={"limit": 200, **params})["items"]


def test_commands_shipped_and_searchable(admin: Api, tacacs_env: dict, linux_devices: dict):
    u = tacacs_env["username"]
    dev = linux_devices["dev1"]

    def shipped():
        rows = _commands(admin, user=u, command="show interfaces brief")
        return rows if {r["record_type"] for r in rows} >= {"start", "stop"} else None

    rows = wait_until(shipped, 30, what="accounting records via the agent")
    stop = next(r for r in rows if r["record_type"] == "stop")
    assert stop["username"] == u and stop["result"] == "accounted"
    assert stop["device_address"] == "127.0.0.1" and stop["device_name"] == dev["hostname"]
    assert stop["source_address"] == "198.51.100.7"
    assert stop["service"] == "shell"
    assert abs((datetime.fromisoformat(stop["timestamp"]) - datetime.now(UTC)).total_seconds()) < 600
    # denied authorization is kept in the command log
    denied = wait_until(lambda: _commands(admin, user=u, result="denied"), 30, what="denied command")
    assert any(r["command"] == "show running-config" for r in denied)
    # search by device hostname and by regex
    assert _commands(admin, device=dev["hostname"], user=u)
    assert any(r["command"] == "show interfaces brief" for r in _commands(admin, user=u, command="~^show int"))
    assert not _commands(admin, user=u, command="~^no-such-command$")


def test_denied_command_raises_alert(admin: Api, tacacs_env: dict):
    u = tacacs_env["username"]

    def alert():
        items = admin.get("/alerts", params={"event_type": "unauthorized_command", "limit": 100})["items"]
        return [a for a in items if u in a["title"] and a["body"] == "show running-config"]

    found = wait_until(alert, 30, what="unauthorized_command alert")
    assert found[0]["severity"] == "high"


def test_auth_events(admin: Api, tacacs_env: dict):
    u = tacacs_env["username"]

    def events():
        ev = admin.get("/tacacs/events", params={"username": u, "limit": 200})["items"]
        kinds = {(e["kind"], e["result"]) for e in ev}
        want = {("authen", "pass"), ("authen", "fail"), ("author", "permit"), ("author", "deny")}
        return ev if want <= kinds else None

    ev = wait_until(events, 30, what="authentication/authorization events")
    authen = [e for e in ev if e["kind"] == "authen"]
    assert all(e["device_address"] == "127.0.0.1" for e in ev)
    assert any("succeeded" in (e["detail"] or "") for e in authen)
    unknown = admin.get("/tacacs/events", params={"username": "no-such-user"})["items"]
    assert any(e["result"] == "fail" for e in unknown)


def test_redeploy_is_idempotent_and_disable_mapping_locks_out(admin: Api, tacacs_env: dict):
    server_id = STACK["tacacs"]["server_id"]
    again = admin.post(f"/tacacs/servers/{server_id}/deploy")
    assert again["version"] == tacacs_env["revision"]["version"]  # nothing changed -> same revision
    admin.patch(f"/tacacs/users/{tacacs_env['mapping']['id']}", {"enabled": False})
    try:
        rev = admin.post(f"/tacacs/servers/{server_id}/deploy")
        assert rev["version"] == tacacs_env["revision"]["version"] + 1
        u, pw = tacacs_env["username"], tacacs_env["password"]
        locked = lambda: not any(tac_client().authenticate(u, pw).valid for _ in range(3))  # noqa: E731
        wait_until(locked, 30, what="user locked out")
    finally:
        admin.patch(f"/tacacs/users/{tacacs_env['mapping']['id']}", {"enabled": True})
        rev = admin.post(f"/tacacs/servers/{server_id}/deploy")
        u, pw = tacacs_env["username"], tacacs_env["password"]
        wait_until(lambda: all(tac_client().authenticate(u, pw).valid for _ in range(3)), 30, what="user re-enabled")
