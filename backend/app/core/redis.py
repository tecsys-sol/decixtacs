"""The one place Redis clients are built (API rate limiter, OIDC state, Celery broker/backend).

Plain ``NOM_REDIS_URL`` or, when ``NOM_REDIS_SENTINELS`` is set, Redis Sentinel: clients then
follow the current master of ``NOM_REDIS_SENTINEL_MASTER``; the password and db number are still
taken from ``NOM_REDIS_URL`` (its host/port are ignored).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from functools import lru_cache
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)


def parse_sentinels(spec: str) -> list[tuple[str, int]]:
    """``"10.0.0.1:26379, sentinel-2"`` -> ``[("10.0.0.1", 26379), ("sentinel-2", 26379)]``."""
    out = []
    for item in (x.strip() for x in spec.split(",")):
        if not item:
            continue
        if item.startswith("["):  # [v6]:port
            host, _, port = item[1:].partition("]")
            port = port.lstrip(":")
        else:
            host, _, port = item.rpartition(":") if item.count(":") == 1 else (item, "", "")
        out.append((host, int(port or 26379)))
    return out


def _url_parts(url: str) -> tuple[str | None, int]:
    u = urlsplit(url)
    db = u.path.lstrip("/")
    return (unquote(u.password) if u.password else None), int(db) if db.isdigit() else 0


def celery_redis_config(s: Settings | None = None) -> dict[str, Any]:
    """Celery ``broker_url``/``result_backend`` (+ transport options when Sentinel is configured)."""
    s = s or get_settings()
    if not s.redis_sentinels:
        return {"broker_url": s.redis_url, "result_backend": s.redis_url}
    password, db = _url_parts(s.redis_url)
    auth = f":{quote(password, safe='')}@" if password else ""
    url = ";".join(f"sentinel://{auth}{h}:{p}/{db}" for h, p in parse_sentinels(s.redis_sentinels))
    opts: dict[str, Any] = {"master_name": s.redis_sentinel_master}
    if s.redis_sentinel_password:
        opts["sentinel_kwargs"] = {"password": s.redis_sentinel_password}
    return {
        "broker_url": url,
        "result_backend": url,
        "broker_transport_options": dict(opts),
        "result_backend_transport_options": dict(opts),
    }


@lru_cache
def redis_client(timeout: float = 0.5):
    """A (lazily connecting) client for the current master. Callers must handle connection errors."""
    import redis

    s = get_settings()
    if not s.redis_sentinels:
        return redis.Redis.from_url(s.redis_url, socket_timeout=timeout, socket_connect_timeout=timeout)
    from redis.sentinel import Sentinel

    password, db = _url_parts(s.redis_url)
    sentinel = Sentinel(
        parse_sentinels(s.redis_sentinels),
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        sentinel_kwargs={"password": s.redis_sentinel_password or None, "socket_timeout": timeout},
    )
    return sentinel.master_for(
        s.redis_sentinel_master, socket_timeout=timeout, socket_connect_timeout=timeout, password=password, db=db
    )


class Breaker:
    """After a Redis error, skip Redis for ``cooldown`` seconds instead of paying the timeout on
    every request."""

    def __init__(self, cooldown: float = 30):
        self.cooldown = cooldown
        self._open_until = 0.0

    @property
    def closed(self) -> bool:
        return time.monotonic() >= self._open_until

    def trip(self) -> None:
        self._open_until = time.monotonic() + self.cooldown


class EphemeralStore:
    """Short-lived, one-time values (OIDC state/PKCE verifier): Redis ``SET EX`` + ``GETDEL`` so any
    API replica can finish a flow another replica started; per-process TTL dict only as a fallback
    while Redis is unreachable (or when no client is configured, e.g. tests)."""

    def __init__(self, prefix: str, client: Any = None, cooldown: float = 30):
        self.prefix = prefix
        self.client = client
        self.breaker = Breaker(cooldown)
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def put(self, key: str, value: dict, ttl: int) -> None:
        raw = json.dumps(value)
        if self.client is not None and self.breaker.closed:
            try:
                self.client.set(self.prefix + key, raw, ex=ttl)
                return
            except Exception:  # noqa: BLE001
                log.warning("redis unavailable, keeping %s* in process memory", self.prefix, exc_info=True)
                self.breaker.trip()
        with self._lock:
            now = time.monotonic()
            self._mem = {k: v for k, v in self._mem.items() if v[0] > now}
            self._mem[key] = (now + ttl, raw)

    def pop(self, key: str) -> dict | None:
        with self._lock:
            item = self._mem.pop(key, None)
        if item is not None:
            return json.loads(item[1]) if item[0] > time.monotonic() else None
        if self.client is not None and self.breaker.closed:
            try:
                raw = self.client.getdel(self.prefix + key)
            except Exception:  # noqa: BLE001
                log.warning("redis unavailable while reading %s*", self.prefix, exc_info=True)
                self.breaker.trip()
                return None
            return json.loads(raw) if raw else None
        return None


def ping() -> str:
    """Readiness helper: ``ok`` | ``down``."""
    try:
        redis_client(0.5).ping()
        return "ok"
    except Exception:  # noqa: BLE001
        return "down"
