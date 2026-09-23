"""Request dependencies: authentication (JWT or API token), tenant context, permission checks."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import decode_access_token, sha256
from app.db.base import aware, utcnow
from app.db.session import get_db
from app.models import ApiToken, Tenant, User
from app.services.rbac import Principal, load_principal

bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    """Everything a handler needs: db session, principal, effective tenant, request metadata."""

    db: Session
    principal: Principal
    tenant_id: uuid.UUID
    ip: str | None
    request_id: str | None

    @property
    def user(self) -> User:
        return self.principal.user


def _load_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.scalar(select(User).where(User.id == user_id).options(selectinload(User.groups)))


def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "authentication required", headers={"WWW-Authenticate": "Bearer"}
        )
    token = creds.credentials
    if token.startswith("nomt_"):
        api = db.scalar(select(ApiToken).where(ApiToken.token_hash == sha256(token), ApiToken.revoked.is_(False)))
        if api is None or (api.expires_at and aware(api.expires_at) < utcnow()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API token")
        user = _load_user(db, api.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token owner disabled")
        api.last_used_at = utcnow()
        db.commit()
        return load_principal(db, user, token_scopes=api.scopes or None)
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    user = _load_user(db, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user disabled")
    return load_principal(db, user)


def get_ctx(
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    x_tenant: str | None = Header(default=None, alias="X-Tenant"),
) -> Ctx:
    tenant_id = principal.tenant_id
    if x_tenant:
        # Platform operators (superusers) may act inside another tenant (MSP model).
        if not principal.user.is_superuser:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-tenant access denied")
        t = db.scalar(select(Tenant).where(Tenant.slug == x_tenant))
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
        tenant_id = t.id
    return Ctx(
        db=db,
        principal=principal,
        tenant_id=tenant_id,
        ip=request.client.host if request.client else None,
        request_id=request.headers.get("X-Request-ID"),
    )


def require(*permissions: str) -> Callable[[Ctx], Ctx]:
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        missing = [p for p in permissions if not ctx.principal.has(p)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {', '.join(missing)}")
        return ctx

    return dep


def get_owned(ctx: Ctx, model, obj_id: uuid.UUID, name: str = "object"):
    """Fetch a tenant-scoped row or 404 (never leak existence across tenants)."""
    obj = ctx.db.get(model, obj_id)
    if obj is None or getattr(obj, "tenant_id", ctx.tenant_id) != ctx.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} not found")
    return obj
