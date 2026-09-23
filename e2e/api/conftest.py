"""Fixtures for the API-level E2E suite. Needs a running stack (e2e/scripts/stack-up.sh).

Everything here talks to real processes: the uvicorn API, the Celery worker, tac_plus-ng (via the
``tacacs_plus`` client) managed by nom-tacacs-agent, and the local sshd acting as linux devices.
Object names carry a per-run suffix so the suite can be re-run against the same stack.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from tacacs_plus.client import TACACSClient

RUN_DIR = Path(os.environ.get("E2E_RUN", Path(__file__).resolve().parents[1] / ".run"))
SUFFIX = os.environ.get("E2E_SUFFIX") or secrets.token_hex(3)


def load_stack() -> dict:
    f = RUN_DIR / "stack.json"
    if not f.exists():
        raise SystemExit(f"{f} not found - start the stack with e2e/scripts/stack-up.sh")
    return json.loads(f.read_text())


STACK = load_stack()


def wait_until(fn: Callable[[], Any], timeout: float = 30, interval: float = 0.5, what: str = "condition") -> Any:
    """Poll ``fn`` until it returns a truthy value (returned) or raise after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        # OSError: connection reset while tac_plus-ng restarts; ValueError: tacacs_plus cannot decode a
        # reply encrypted with the previous NAS key (the old configuration still answers until the
        # master process has handled SIGHUP - "only checking for signals every couple of seconds")
        except (AssertionError, httpx.HTTPError, KeyError, OSError, ValueError) as exc:
            last_exc = exc
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}" + (f": {last_exc!r}" if last_exc else ""))


class Api:
    """Small authenticated client; logs in again when the (15 min) access token expired."""

    def __init__(self, username: str, password: str, tenant: str | None = None, otp: str | None = None):
        self.username, self.password, self.tenant, self.otp = username, password, tenant, otp
        self.http = httpx.Client(base_url=STACK["api_url"] + "/api/v1", timeout=60)
        self.login()

    def login(self) -> None:
        r = self.http.post(
            "/auth/login",
            json={"username": self.username, "password": self.password, "tenant": self.tenant, "otp": self.otp},
        )
        assert r.status_code == 200, r.text
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def request(self, method: str, url: str, expect: int | None = None, **kw) -> httpx.Response:
        r = self.http.request(method, url, **kw)
        if r.status_code == 401 and "Authorization" in self.http.headers:
            self.login()
            r = self.http.request(method, url, **kw)
        if expect is not None:
            assert r.status_code == expect, f"{method} {url} -> {r.status_code}: {r.text[:500]}"
        return r

    def get(self, url: str, **kw) -> Any:
        return self.request("GET", url, expect=kw.pop("expect", 200), **kw).json()

    def post(self, url: str, json: Any = None, expect: int | None = None, **kw) -> Any:
        r = self.request("POST", url, json=json, **kw)
        if expect is None:
            assert r.status_code in (200, 201, 204), f"POST {url} -> {r.status_code}: {r.text[:500]}"
        else:
            assert r.status_code == expect, f"POST {url} -> {r.status_code}: {r.text[:500]}"
        return r.json() if r.content else None

    def put(self, url: str, json: Any = None, **kw) -> Any:
        return self.request("PUT", url, json=json, expect=200, **kw).json()

    def patch(self, url: str, json: Any = None, **kw) -> Any:
        return self.request("PATCH", url, json=json, expect=200, **kw).json()

    def delete(self, url: str, **kw) -> None:
        r = self.request("DELETE", url, **kw)
        assert r.status_code in (204, 404), r.text


@pytest.fixture(scope="session")
def stack() -> dict:
    return STACK


@pytest.fixture(scope="session")
def suffix() -> str:
    return SUFFIX


@pytest.fixture(scope="session")
def admin() -> Api:
    t = STACK["tenants"]["e2e"]
    return Api(t["username"], t["password"], "e2e")


@pytest.fixture(scope="session")
def agent_http() -> httpx.Client:
    """Client authenticated with the TACACS server's agent token (like nom-tacacs-agent)."""
    return httpx.Client(
        base_url=STACK["api_url"] + "/api/v1",
        headers={"Authorization": f"Bearer {STACK['tacacs']['agent_token']}"},
        timeout=30,
    )


# --- TACACS ------------------------------------------------------------------------------------

NAS_KEY = "e2e-nas-secret-" + SUFFIX
TAC_PASSWORD = "Tac-E2e-Pa55word!"


def tac_client() -> TACACSClient:
    t = STACK["tacacs"]
    return TACACSClient(t["host"], t["port"], NAS_KEY, timeout=10)


@pytest.fixture(scope="session")
def tacacs_env(admin: Api, suffix: str, linux_devices: dict) -> dict:
    return setup_tacacs_env(admin, suffix, linux_devices)


def setup_tacacs_env(admin: Api, suffix: str, linux_devices: dict) -> dict:
    """Platform objects for the TACACS flow, deployed and installed by the real agent.

    group noc-SFX + user alice-SFX (TACACS password) -> policy noc-ro-SFX: priv 1, only on NAS in
    device group lab-SFX, ``show running-config`` denied (seq 5), ``show ...`` permitted, default deny.
    """
    # a previous run's NAS entry for 127.0.0.1 would clash with ours (one address, one key)
    for n in admin.get("/tacacs/devices"):
        if n["address"] == "127.0.0.1":
            admin.delete(f"/tacacs/devices/{n['id']}")
    group = admin.post("/groups", {"name": f"noc-{suffix}", "description": "E2E NOC"})
    user = admin.post(
        "/users",
        {
            "username": f"alice-{suffix}",
            "full_name": "Alice E2E",
            "email": f"alice-{suffix}@e2e.example",
            "password": "Portal-E2e-Pa55!",
            "group_ids": [group["id"]],
        },
    )
    dgroup = admin.post(
        "/device-groups",
        {"name": f"lab-{suffix}", "kind": "custom", "device_ids": [linux_devices["dev1"]["id"]]},
    )
    nas = admin.post(
        "/tacacs/devices",
        {
            "name": f"e2e-local-{suffix}",
            "address": "127.0.0.1",
            "key": NAS_KEY,
            "vendor": "cisco",
            "device_id": linux_devices["dev1"]["id"],
            "device_group_id": dgroup["id"],
        },
    )
    policy = admin.post(
        "/tacacs/policies",
        {
            "name": f"noc-ro-{suffix}",
            "priority": 10,
            "group_id": group["id"],
            "device_group_id": dgroup["id"],
            "privilege_level": 1,
            "default_action": "deny",
            "command_rules": [
                {"sequence": 5, "action": "deny", "pattern": "^show running-config", "alert_on_match": True},
                {"sequence": 10, "action": "permit", "pattern": "^show "},
                {"sequence": 20, "action": "permit", "pattern": "^ping "},
            ],
        },
    )
    mapping = admin.post(
        "/tacacs/users", {"user_id": user["id"], "auth_method": "crypt", "password": TAC_PASSWORD}
    )
    server_id = STACK["tacacs"]["server_id"]
    rev = admin.post(f"/tacacs/servers/{server_id}/deploy")
    server = next(s for s in admin.get("/tacacs/servers") if s["id"] == server_id)
    assert server["config_sha256"] == rev["sha256"]
    cfg = Path(STACK["tacacs"]["config_path"])

    def installed() -> bool:
        return cfg.exists() and hashlib.sha256(cfg.read_bytes()).hexdigest() == rev["sha256"]

    wait_until(installed, 30, what="agent to install the deployed revision")

    # tac_plus-ng reloads asynchronously after SIGHUP: wait until the new user can log in, three
    # times in a row (new connections are then served by the restarted master's children)
    def can_login() -> bool:
        return all(tac_client().authenticate(f"alice-{suffix}", TAC_PASSWORD).valid for _ in range(3))

    wait_until(can_login, 30, what="tac_plus-ng to serve the new configuration")
    return {
        "group": group,
        "user": user,
        "username": f"alice-{suffix}",
        "password": TAC_PASSWORD,
        "device_group": dgroup,
        "nas": nas,
        "policy": policy,
        "mapping": mapping,
        "revision": rev,
    }


# --- inventory: the local sshd as linux devices -----------------------------------------------


def write_device_config(user: str, text: str) -> None:
    Path(STACK["ssh"]["config_files"][user]).write_text(text)


def read_device_config(user: str) -> str:
    return Path(STACK["ssh"]["config_files"][user]).read_text()


@pytest.fixture(scope="session")
def linux_devices(admin: Api, suffix: str) -> dict:
    return setup_linux_devices(admin, suffix)


def setup_linux_devices(admin: Api, suffix: str) -> dict:
    """Two linux devices served by the stack's sshd (127.0.0.1 / 127.0.0.2), one credential each."""
    ssh = STACK["ssh"]
    linux = next(p for p in admin.get("/platforms") if p["slug"] == "linux")
    site = admin.post("/sites", {"name": f"E2E Lab {suffix}", "slug": f"e2e-lab-{suffix}", "kind": "pop"})
    # only one inventory device per management address in this tenant (accounting correlates by IP)
    for d in admin.get("/devices", params={"limit": 500})["items"]:
        if d["management_ip"] in ("127.0.0.1", "127.0.0.2"):
            admin.delete(f"/devices/{d['id']}")
    out = {}
    for key, user, ip in (("dev1", ssh["users"][0], "127.0.0.1"), ("dev2", ssh["users"][1], "127.0.0.2")):
        cred = admin.post(
            "/credentials", {"name": f"{user}-{suffix}", "username": user, "password": ssh["password"]}
        )
        dev = admin.post(
            "/devices",
            {
                "hostname": f"e2e-{key}-{suffix}",
                "management_ip": ip,
                "ssh_port": ssh["port"],
                "site_id": site["id"],
                "platform_id": linux["id"],
                "credential_id": cred["id"],
                "role": "server",
            },
        )
        out[key] = {**dev, "ssh_user": user}
    out["site"] = site
    return out
