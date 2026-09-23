"""Fixed-window rate limiter (Redis backed, in-memory fallback)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis_url: str | None):
        self._mem: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        self._redis = None
        if redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(redis_url, socket_timeout=0.2, socket_connect_timeout=0.2)
                self._redis.ping()
            except Exception:  # noqa: BLE001
                log.warning("rate limiter: redis unavailable, using per-process memory")
                self._redis = None

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        bucket = int(time.time() // window)
        k = f"rl:{key}:{bucket}"
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(k)
                pipe.expire(k, window + 1)
                count = int(pipe.execute()[0])
                return count <= limit, max(limit - count, 0)
            except Exception:  # noqa: BLE001
                pass
        b, count = self._mem[key]
        count = count + 1 if b == bucket else 1
        self._mem[key] = (bucket, count)
        return count <= limit, max(limit - count, 0)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        path = request.url.path
        if not path.startswith(s.api_prefix):
            return await call_next(request)
        ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "?").split(",")[0].strip()
        sensitive = path.endswith(("/auth/login", "/auth/refresh", "/auth/mfa/verify"))
        limit = s.rate_limit_login if sensitive else s.rate_limit_api
        key = f"{'auth' if sensitive else 'api'}:{ip}"
        ok, remaining = self.limiter.hit(key, limit, s.rate_limit_window_seconds)
        if not ok:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(s.rate_limit_window_seconds)})
        resp = await call_next(request)
        resp.headers["X-RateLimit-Limit"] = str(limit)
        resp.headers["X-RateLimit-Remaining"] = str(remaining)
        return resp
