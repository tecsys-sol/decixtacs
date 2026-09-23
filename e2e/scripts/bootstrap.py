"""Post-start bootstrap of the E2E stack (run by stack-up.sh once the API answers).

* creates the TACACS+ server object (address/port of the local tac_plus-ng) via the API and
  stores its one-time agent token in $E2E_RUN/agent-token (read by the tacacs-agent);
* writes $E2E_RUN/stack.json - everything the API and browser suites need to find the stack.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

RUN = Path(os.environ["E2E_RUN"])
API = os.environ["E2E_API_URL"] + "/api/v1"


def wait_api(timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(os.environ["E2E_API_URL"] + "/healthz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    sys.exit("API did not become healthy")


def login(username: str, password: str, tenant: str) -> httpx.Client:
    r = httpx.post(f"{API}/auth/login", json={"username": username, "password": password, "tenant": tenant})
    r.raise_for_status()
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {r.json()['access_token']}"}, timeout=30)


def main() -> None:
    wait_api()
    admin = login(os.environ["E2E_ADMIN_USER"], os.environ["E2E_ADMIN_PASSWORD"], "e2e")
    port = int(os.environ["E2E_TACACS_PORT"])
    servers = admin.get("/tacacs/servers").raise_for_status().json()
    token_file = RUN / "agent-token"
    server = next((s for s in servers if s["name"] == "e2e-tac"), None)
    if server is None or not token_file.exists():
        if server is not None:  # token lost: recreate the server object
            admin.delete(f"/tacacs/servers/{server['id']}").raise_for_status()
        server = admin.post(
            "/tacacs/servers", json={"name": "e2e-tac", "address": "127.0.0.1", "port": port}
        ).raise_for_status().json()
        token_file.write_text(server["agent_token"] + "\n")
        token_file.chmod(0o600)
    ssh_users = os.environ["E2E_SSH_USERS"].split()
    stack = {
        "api_url": os.environ["E2E_API_URL"],
        "web_url": os.environ["E2E_WEB_URL"],
        "run_dir": str(RUN),
        "tacacs": {
            "host": "127.0.0.1",
            "port": port,
            "server_id": server["id"],
            "agent_token": token_file.read_text().strip(),
            "log_dir": str(RUN / "tac" / "log"),
            "config_path": str(RUN / "tac" / "tac_plus-ng.cfg"),
        },
        "ssh": {
            "host": "127.0.0.1",
            "port": int(os.environ["E2E_SSH_PORT"]),
            "password": os.environ["E2E_SSH_PASSWORD"],
            "users": ssh_users,
            # the linux platform's backup command is "cat ~/device.conf"; ~/device.conf of every
            # device user is a symlink to this writable file
            "config_files": {u: str(RUN / "devices" / f"{u}.conf") for u in ssh_users},
        },
        "tenants": {
            "e2e": {"username": os.environ["E2E_ADMIN_USER"], "password": os.environ["E2E_ADMIN_PASSWORD"]},
            "acme": {"username": os.environ["E2E_OPERATOR_USER"], "password": os.environ["E2E_OPERATOR_PASSWORD"]},
            "demo": {"username": os.environ["E2E_DEMO_USER"], "password": os.environ["E2E_DEMO_PASSWORD"]},
        },
    }
    (RUN / "stack.json").write_text(json.dumps(stack, indent=2) + "\n")
    print(f"TACACS server {server['id']} (port {port}); wrote {RUN / 'stack.json'}")


if __name__ == "__main__":
    main()
