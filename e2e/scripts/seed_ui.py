"""Prepare data for the Playwright suite (run by e2e/tests/global-setup.ts) and write
$E2E_RUN/ui-seed.json.

Uses the same helpers as the API suite: linux devices on the local sshd, a TACACS policy/user
deployed through the real agent, and real TACACS+ traffic against tac_plus-ng (including a denied
and a "dangerous" command) so the accounting pages show data that went through the whole pipeline.
Also creates the users the RBAC / four-eyes / MFA specs log in with and uploads an asciicast.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

os.environ.setdefault("E2E_SUFFIX", "ui" + secrets.token_hex(2))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import httpx  # noqa: E402
from conftest import (  # noqa: E402
    RUN_DIR,
    STACK,
    SUFFIX,
    Api,
    setup_linux_devices,
    setup_tacacs_env,
    tac_client,
    wait_until,
)
from tacacs_plus.flags import TAC_PLUS_ACCT_FLAG_STOP  # noqa: E402

PASSWORD = "Ui-E2e-Str0ng-Pa55!"


def role_id(admin: Api, name: str) -> str:
    return next(r["id"] for r in admin.get("/roles") if r["name"] == name)


def make_user(admin: Api, username: str, role: str, full_name: str) -> dict:
    u = admin.post(
        "/users",
        {"username": username, "full_name": full_name, "email": f"{username}@e2e.example", "password": PASSWORD},
    )
    admin.post("/role-bindings", {"role_id": role_id(admin, role), "user_id": u["id"]})
    return {"id": u["id"], "username": username, "password": PASSWORD}


def tacacs_traffic(username: str, password: str) -> None:
    assert tac_client().authenticate(username, password, rem_addr="203.0.113.9", port="vty2").valid
    assert not tac_client().authenticate(username, "wrong-" + password, rem_addr="203.0.113.9").valid
    cmds = ["show bgp summary", "show running-config", "request system reboot"]
    for cmd in cmds:
        words = cmd.split()
        tac_client().authorize(
            username, arguments=[b"service=shell", f"cmd={words[0]}".encode(),
                                 *[f"cmd-arg={w}".encode() for w in words[1:]]],
            rem_addr="203.0.113.9", port="vty2",
        )  # fmt: skip
    for cmd in ("show bgp summary", "request system reboot", "configure terminal"):
        assert tac_client().account(
            username, TAC_PLUS_ACCT_FLAG_STOP,
            arguments=[b"task_id=77", b"service=shell", b"priv-lvl=15", f"cmd={cmd}".encode()],
            rem_addr="203.0.113.9", port="vty2",
        ).valid  # fmt: skip


def upload_cast(username: str) -> dict:
    lines = [
        {"version": 2, "width": 100, "height": 30, "timestamp": 1790000000, "title": "e2e session"},
        [0.2, "o", "e2e-router> "],
        [0.8, "i", "show version\r"],
        [0.9, "o", "show version\r\n"],
        [1.2, "o", "Junos: 23.4R1.9 (E2E replay marker)\r\n"],
        [1.4, "o", "e2e-router> "],
        [2.0, "i", "exit\r"],
        [2.1, "o", "exit\r\n"],
    ]
    cast = "\n".join(json.dumps(x) for x in lines) + "\n"
    r = httpx.post(
        STACK["api_url"] + "/api/v1/sessions",
        headers={"Authorization": f"Bearer {STACK['tacacs']['agent_token']}"},
        files={"file": ("e2e.cast", cast.encode(), "application/x-asciicast")},
        data={"username": username, "device_address": "127.0.0.1", "source_address": "203.0.113.9"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main() -> None:
    t = STACK["tenants"]["e2e"]
    admin = Api(t["username"], t["password"], "e2e")
    devices = setup_linux_devices(admin, SUFFIX)
    tac = setup_tacacs_env(admin, SUFFIX, devices)
    tacacs_traffic(tac["username"], tac["password"])
    wait_until(
        lambda: admin.get("/accounting/commands", params={"user": tac["username"], "command": "request system"})[
            "items"
        ],
        45,
        what="accounting records of the UI seed",
    )
    ssh = STACK["ssh"]
    cred = admin.post(
        "/credentials", {"name": f"ui-cred-{SUFFIX}", "username": ssh["users"][1], "password": ssh["password"]}
    )
    rec = upload_cast(tac["username"])
    seed = {
        "suffix": SUFFIX,
        "devices": {k: {"id": v["id"], "hostname": v["hostname"]} for k, v in devices.items() if k != "site"},
        "site": devices["site"]["name"],
        "tacacs_user": tac["username"],
        "credential": {"id": cred["id"], "name": cred["name"], "ssh_user": ssh["users"][1]},
        "device_config_file": ssh["config_files"][ssh["users"][1]],
        "recording_id": rec["id"],
        "users": {
            "viewer": make_user(admin, f"viewer-{SUFFIX}", "read-only", "Read Only Viewer"),
            "requester": make_user(admin, f"requester-{SUFFIX}", "change-manager", "Change Requester"),
            "approver": make_user(admin, f"approver-{SUFFIX}", "change-manager", "Change Approver"),
            "mfa": make_user(admin, f"mfa-{SUFFIX}", "admin", "MFA User"),
        },
    }
    out = RUN_DIR / "ui-seed.json"
    out.write_text(json.dumps(seed, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
