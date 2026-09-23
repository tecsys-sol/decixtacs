"""NetworkOps Manager API entrypoint."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.v1 import activity, auth, configs, inventory, ops, tacacs, users
from app.core.config import get_settings
from app.core.ratelimit import RateLimiter, RateLimitMiddleware
from app.services import metrics

log = logging.getLogger("nom")

TAGS = [
    {"name": "auth", "description": "Login (local, LDAP/AD, OIDC), MFA, refresh tokens, API tokens"},
    {"name": "users", "description": "Users, groups, roles, RBAC/ABAC bindings, tenants"},
    {"name": "inventory", "description": "Sites, racks, devices, device groups, credentials, topology"},
    {"name": "tacacs", "description": "TACACS+ servers, NAS clients, policies, users, tac_plus-ng render/deploy"},
    {"name": "configs", "description": "Backups, diffs, restore, drift, golden configs, compliance, config search"},
    {"name": "activity", "description": "Command accounting, session recordings, audit trail, change requests"},
    {"name": "operations", "description": "NetBox/IXP Manager, route servers, alerts, reports, dashboard, search"},
]


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version="1.0.0",
        description="Network Access & Configuration Management Platform - TACACS+ AAA, config backup, "
                    "compliance, accounting and change management for ISPs, IXPs and MSPs.",
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(s.redis_url if s.environment != "test" else None))

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        metrics.HTTP_REQUESTS.labels(request.method, getattr(route, "path", "unmatched"),
                                     str(response.status_code)).observe(time.perf_counter() - start)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if s.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    for r in (auth.router, users.router, inventory.router, tacacs.router, configs.router, activity.router, ops.router):
        app.include_router(r, prefix=s.api_prefix)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        from app.db.session import engine

        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
