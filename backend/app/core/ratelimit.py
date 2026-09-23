"""Fixed-window rate limiter (Redis backed, in-memory fallback)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.redis import Breaker

log = logging.getLogger(__name__)


class RateLimiter:
    """``client`` comes from :func:`app.core.redis.redis_client` (plain or Sentinel master). While
    Redis is unreachable the limiter counts per process and retries Redis after a cool-down."""

    def __init__(self, client=None):
        self._mem: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        self._redis = client
        self._breaker = Breaker(30)

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        bucket = int(time.time() // window)
        k = f"rl:{key}:{bucket}"
        if self._redis is not None and self._breaker.closed:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(k)
                pipe.expire(k, window + 1)
                count = int(pipe.execute()[0])
                return count <= limit, max(limit - count, 0)
            except Exception:  # noqa: BLE001
                log.warning("rate limiter: redis unavailable, counting per process for 30s", exc_info=True)
                self._breaker.trip()
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
        ip = (
            request.headers.get("X-Forwarded-For", request.client.host if request.client else "?").split(",")[0].strip()
        )
        sensitive = path.endswith(("/auth/login", "/auth/refresh", "/auth/mfa/verify"))
        limit = s.rate_limit_login if sensitive else s.rate_limit_api
        key = f"{'auth' if sensitive else 'api'}:{ip}"
        ok, remaining = self.limiter.hit(key, limit, s.rate_limit_window_seconds)
        if not ok:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(s.rate_limit_window_seconds)},
            )
        resp = await call_next(request)
        resp.headers["X-RateLimit-Limit"] = str(limit)
        resp.headers["X-RateLimit-Remaining"] = str(remaining)
        return resp
