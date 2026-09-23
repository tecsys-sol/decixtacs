from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from networkops._client import BaseClient
from networkops.models import Me, parse
from networkops.resources import Accounting, Audit, Backups, Changes, Compliance, Devices, Tacacs


class NetworkOpsClient(BaseClient):
    """Synchronous NetworkOps Manager client.

    Authentication, one of:

    * ``token="nomt_..."`` - an API token (``POST /auth/tokens``), optionally scoped;
    * ``username=``/``password=`` (+ ``tenant=`` slug, ``otp=`` or ``otp_provider=`` for MFA) - the
      client logs in lazily, refreshes the 15-minute access token before it expires using the
      rotating refresh token, and re-authenticates if the refresh token was revoked.

    ``act_as_tenant="slug"`` sends ``X-Tenant`` (platform superusers acting inside a tenant).
    Idempotent requests are retried on 429/502/503/504 and connection errors (``max_retries``).
    """

    def __init__(self, base_url: str, *, token: str | None = None, username: str | None = None,
                 password: str | None = None, tenant: str | None = None, otp: str | None = None,
                 otp_provider: Callable[[], str] | None = None, act_as_tenant: str | None = None,
                 timeout: float = 30.0, max_retries: int = 2, verify: bool | str = True,
                 transport: httpx.BaseTransport | None = None, **kw: Any):
        super().__init__(base_url, token=token, username=username, password=password, tenant=tenant, otp=otp,
                         otp_provider=otp_provider, act_as_tenant=act_as_tenant, timeout=timeout,
                         max_retries=max_retries, verify=verify, transport=transport, **kw)
        self.devices = Devices(self)
        self.backups = Backups(self)
        self.tacacs = Tacacs(self)
        self.accounting = Accounting(self)
        self.compliance = Compliance(self)
        self.changes = Changes(self)
        self.audit = Audit(self)

    def __enter__(self) -> NetworkOpsClient:
        return self

    def me(self) -> Me:
        return parse(Me, self.get("/auth/me"))

    def create_api_token(self, name: str, scopes: list[str] | None = None) -> dict[str, Any]:
        """Create a (scoped) API token for automation; ``token`` in the result is shown once."""
        result: dict[str, Any] = self.post("/auth/tokens", json={"name": name, "scopes": scopes or []})
        return result

    def search(self, q: str) -> Any:
        """Global search across devices, users, configs, changes..."""
        return self.get("/search", params={"q": q})
