"""HTTP client for the NetworkOps Manager agent endpoints (authenticated with the agent token).

* ``GET  /tacacs/agent/config``     - rendered tac_plus-ng config (ETag = sha256, If-None-Match)
* ``POST /tacacs/agent/heartbeat``  - {running_sha256, status: ok|error, message}
* ``POST /accounting/ingest``       - {lines: [...]} raw tac_plus-ng log lines
* ``POST /sessions``                - multipart asciicast v2 upload
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from nom_tacacs_agent import __version__

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


_SHA256 = re.compile(r"[0-9a-f]{64}")


def config_sha256(headers) -> str | None:
    """sha256 of the deployed config. Prefer X-Config-Sha256 (proxies leave custom headers alone);
    fall back to the ETag, which reverse proxies may rewrite - Caddy's ``encode`` appends ``-gzip``,
    others add ``W/`` or quotes - so extract the 64-hex digest from it."""
    for value in (headers.get("X-Config-Sha256"), headers.get("ETag")):
        m = _SHA256.search((value or "").lower())
        if m:
            return m.group(0)
    return None


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    @property
    def retryable(self) -> bool:
        # Transport errors (no status) and transient HTTP errors are retried. 401/403 are also
        # retried by the loops (token may be fixed server side) but logged loudly.
        return self.status_code is None or self.status_code in RETRYABLE_STATUS

    @property
    def permanent(self) -> bool:
        """The request itself is bad and will never succeed as-is."""
        return self.status_code in (400, 413, 415, 422)


@dataclass
class ConfigResponse:
    state: Literal["changed", "unchanged", "not_deployed", "conflict"]
    content: str = ""
    etag: str | None = None
    version: int | None = None
    detail: str = ""


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class AgentAPI:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify: bool | str = True,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "User-Agent": f"nom-tacacs-agent/{__version__}"},
            verify=verify,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ApiError(f"{method} {path}: {exc.__class__.__name__}: {exc}") from exc
        return r

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        body = r.text[:500]
        detail = body
        try:
            detail = json.dumps(r.json().get("detail"))
        except (ValueError, AttributeError):
            pass
        raise ApiError(
            f"{r.request.method} {r.request.url.path} -> HTTP {r.status_code}: {detail}", r.status_code, body
        )

    # --- config -----------------------------------------------------------------------------

    def fetch_config(self, etag: str | None) -> ConfigResponse:
        headers = {"If-None-Match": etag} if etag else {}
        r = self._request("GET", "/tacacs/agent/config", headers=headers)
        if r.status_code == 304:
            return ConfigResponse("unchanged", etag=etag)
        if r.status_code == 404:
            return ConfigResponse("not_deployed", detail=_detail(r))
        if r.status_code == 409:
            return ConfigResponse("conflict", detail=_detail(r))
        if r.status_code != 200:
            self._raise(r)
        version = r.headers.get("X-Config-Version")
        return ConfigResponse(
            "changed",
            content=r.text,
            etag=config_sha256(r.headers),
            version=int(version) if version and version.isdigit() else None,
        )

    def heartbeat(self, running_sha256: str | None, status: str = "ok", message: str | None = None) -> None:
        r = self._request(
            "POST",
            "/tacacs/agent/heartbeat",
            json={"running_sha256": running_sha256, "status": status, "message": (message or "")[:4000] or None},
        )
        if r.status_code not in (200, 204):
            self._raise(r)

    # --- accounting --------------------------------------------------------------------------

    def ingest(self, lines: list[str]) -> dict:
        r = self._request("POST", "/accounting/ingest", json={"lines": lines})
        if r.status_code != 200:
            self._raise(r)
        return r.json()

    # --- session recordings --------------------------------------------------------------------

    def upload_recording(self, path: Path, meta: dict[str, str]) -> dict:
        data = {k: v for k, v in meta.items() if v}
        with path.open("rb") as fh:
            r = self._request(
                "POST", "/sessions", data=data, files={"file": (path.name, fh, "application/x-asciicast")}
            )
        if r.status_code not in (200, 201):
            self._raise(r)
        return r.json()


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail", ""))
    except (ValueError, AttributeError):
        return r.text[:300]
