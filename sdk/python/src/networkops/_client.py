"""HTTP core: authentication (API token or username/password with automatic refresh), retries,
error mapping and pagination."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

import httpx

from networkops import __version__
from networkops.errors import APIError, MFARequiredError, RateLimitError, error_for
from networkops.models import Model, Page, TokenPair, parse

M = TypeVar("M", bound=Model)

IDEMPOTENT = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
RETRY_STATUS = {429, 502, 503, 504}


def _param(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: _param(v) for k, v in (params or {}).items() if v is not None}


def jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, (datetime, UUID)):
        return _param(v)
    return v


class _Session:
    """Holds the credentials and the current access/refresh token pair (thread-safe)."""

    def __init__(self, *, token: str | None, username: str | None, password: str | None, tenant: str | None,
                 otp: str | None, otp_provider: Callable[[], str] | None, refresh_skew: float = 30.0):
        if token and (username or password):
            raise ValueError("pass either token= or username=/password=, not both")
        if not token and not (username and password):
            raise ValueError("authentication required: token= (API token) or username= and password=")
        self.static_token = token
        self.username, self.password, self.tenant = username, password, tenant
        self.otp, self.otp_provider = otp, otp_provider
        self.refresh_skew = refresh_skew
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at = 0.0
        self.lock = threading.RLock()

    def store(self, pair: TokenPair, now: float) -> None:
        self.access_token, self.refresh_token = pair.access_token, pair.refresh_token
        self.expires_at = now + pair.expires_in

    def clear(self) -> None:
        self.access_token = self.refresh_token = None
        self.expires_at = 0.0


class BaseClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        tenant: str | None = None,
        otp: str | None = None,
        otp_provider: Callable[[], str] | None = None,
        act_as_tenant: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        base = base_url.rstrip("/")
        if not base.endswith("/api/v1"):
            base += "/api/v1"
        headers = {"User-Agent": f"networkops-python/{__version__}", "Accept": "application/json"}
        if act_as_tenant:
            headers["X-Tenant"] = act_as_tenant  # superusers (MSP operators) only
        self._http = http_client or httpx.Client(base_url=base, headers=headers, timeout=timeout,
                                                 verify=verify, transport=transport)
        self._owns_http = http_client is None
        self._session = _Session(token=token, username=username, password=password, tenant=tenant, otp=otp,
                                 otp_provider=otp_provider)
        self.max_retries = max_retries
        self._clock, self._sleep = clock, sleep

    # --- lifecycle ------------------------------------------------------------------------

    def close(self) -> None:
        """Revoke the refresh-token family (password sessions) and close the connection pool."""
        s = self._session
        if s.refresh_token:
            try:
                self._http.post("/auth/logout", json={"refresh_token": s.refresh_token})
            except httpx.HTTPError:
                pass
            s.clear()
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BaseClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- authentication -------------------------------------------------------------------

    def _login(self) -> None:
        s = self._session
        body: dict[str, Any] = {"username": s.username, "password": s.password}
        if s.tenant:
            body["tenant"] = s.tenant
        otp = s.otp_provider() if s.otp_provider else s.otp
        if otp:
            body["otp"] = otp
        r = self._http.post("/auth/login", json=body)
        if r.status_code != 200:
            err = self._error(r)
            if err.code == "mfa_required":
                raise MFARequiredError(err.status_code, err.detail, method="POST", path="/auth/login")
            raise err
        s.store(parse(TokenPair, r.json()), self._clock())

    def _refresh(self) -> bool:
        s = self._session
        if not s.refresh_token:
            return False
        r = self._http.post("/auth/refresh", json={"refresh_token": s.refresh_token})
        if r.status_code != 200:
            s.clear()  # expired, revoked or reuse detected -> fall back to a fresh login
            return False
        s.store(parse(TokenPair, r.json()), self._clock())
        return True

    def _bearer(self, force_renew: bool = False) -> str:
        s = self._session
        if s.static_token:
            return s.static_token
        with s.lock:
            stale = s.access_token is None or self._clock() >= s.expires_at - s.refresh_skew
            if force_renew or stale:
                if not self._refresh():
                    self._login()
            assert s.access_token is not None
            return s.access_token

    def login(self) -> None:
        """Authenticate eagerly (otherwise the first request does it)."""
        self._bearer()

    # --- requests ---------------------------------------------------------------------------

    @staticmethod
    def _error(r: httpx.Response) -> APIError:
        try:
            detail: Any = r.json().get("detail", r.text)
        except (ValueError, AttributeError):
            detail = r.text
        cls = error_for(r.status_code)
        kw: dict[str, Any] = {"method": r.request.method, "path": r.request.url.path,
                              "request_id": r.headers.get("X-Request-ID")}
        if cls is RateLimitError:
            ra = r.headers.get("Retry-After")
            return RateLimitError(r.status_code, detail, retry_after=float(ra) if ra else None, **kw)
        return cls(r.status_code, detail, **kw)

    def request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any = None,
                data: Any = None, files: Any = None, expect: str = "json") -> Any:
        method = method.upper()
        attempt = 0
        renewed = False
        while True:
            headers = {"Authorization": f"Bearer {self._bearer()}"}
            try:
                r = self._http.request(method, path, params=clean_params(params),
                                       json=jsonable(json) if json is not None else None,
                                       data=data, files=files, headers=headers)
            except httpx.TransportError:
                if method in IDEMPOTENT and attempt < self.max_retries:
                    attempt += 1
                    self._sleep(self._backoff(attempt))
                    continue
                raise
            if r.status_code == 401 and not renewed and not self._session.static_token:
                # access token revoked/expired early (clock skew, key rotation): renew once
                renewed = True
                with self._session.lock:
                    self._session.access_token = None
                continue
            if r.status_code in RETRY_STATUS and attempt < self.max_retries and (
                    method in IDEMPOTENT or r.status_code == 429):
                attempt += 1
                ra = r.headers.get("Retry-After")
                self._sleep(float(ra) if ra and r.status_code == 429 else self._backoff(attempt))
                continue
            if r.status_code >= 400:
                raise self._error(r)
            if r.status_code == 204 or expect == "none":
                return None
            if expect == "text":
                return r.text
            return r.json()

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(8.0, 0.5 * 2.0 ** (attempt - 1)) * (0.5 + random.random() / 2))  # noqa: S311

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, expect="none", **kw)

    # --- pagination --------------------------------------------------------------------------

    def get_page(self, path: str, model: type[M], params: Mapping[str, Any] | None = None, *,
                 limit: int = 100, offset: int = 0) -> Page[M]:
        data = self.get(path, params={**(params or {}), "limit": limit, "offset": offset})
        return Page(items=[parse(model, i) for i in data["items"]], total=data["total"], limit=data["limit"],
                    offset=data["offset"])

    def iterate(self, path: str, model: type[M], params: Mapping[str, Any] | None = None, *,
                page_size: int = 100, max_items: int | None = None) -> Iterator[M]:
        """Yield every item of a paginated (``{items,total,limit,offset}``) endpoint."""
        offset, seen = 0, 0
        while True:
            page = self.get_page(path, model, params, limit=page_size, offset=offset)
            for item in page.items:
                yield item
                seen += 1
                if max_items is not None and seen >= max_items:
                    return
            offset += len(page.items)
            if not page.items or offset >= page.total:
                return
