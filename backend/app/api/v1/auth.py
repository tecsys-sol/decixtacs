"""Authentication: login (local/LDAP/AD), OIDC SSO, MFA enrolment, refresh rotation, API tokens."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

import httpx
import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, get_ctx
from app.api.v1.common import ORM
from app.core.config import get_settings
from app.core.security import (
    PasswordPolicyError,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    new_opaque_token,
    validate_password_policy,
    verify_password,
)
from app.db.base import utcnow
from app.db.session import get_db
from app.models import ApiToken, Group, User
from app.services import audit
from app.services.auth import login as login_svc
from app.services.auth import oidc

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str
    tenant: str | None = None
    otp: str | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class MeOut(ORM):
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    email: str | None
    full_name: str | None
    is_superuser: bool
    mfa_enabled: bool
    auth_source: str
    permissions: list[str] = []
    groups: list[str] = []


def _tok(p: login_svc.TokenPair) -> TokenOut:
    return TokenOut(access_token=p.access_token, refresh_token=p.refresh_token, expires_in=p.expires_in)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    try:
        pair = login_svc.password_login(
            db,
            body.tenant,
            body.username,
            body.password,
            body.otp,
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
    except login_svc.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": e.code, "message": str(e)}) from e
    return _tok(pair)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        return _tok(login_svc.refresh(db, body.refresh_token))
    except login_svc.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": e.code, "message": str(e)}) from e


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    login_svc.logout(db, body.refresh_token)


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx = Depends(get_ctx)):
    u = ctx.user
    fields = {k: getattr(u, k) for k in MeOut.model_fields if k not in ("permissions", "groups")}
    return MeOut(**fields, permissions=sorted(ctx.principal.permissions), groups=[g.name for g in u.groups])


class ProfileIn(BaseModel):
    full_name: str | None = None
    email: str | None = None


@router.patch("/me", response_model=MeOut)
def update_me(body: ProfileIn, ctx: Ctx = Depends(get_ctx)):
    """Change your own display name / email (directory users: until the next sync overwrites it)."""
    u = ctx.user
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(u, k) for k in data}
    if "full_name" in data:
        name = (data["full_name"] or "").strip()
        if len(name) > 255:
            raise HTTPException(422, "name is too long")
        u.full_name = name or None
    if "email" in data:
        email = (data["email"] or "").strip()
        if email and ("@" not in email or len(email) > 255):
            raise HTTPException(422, "invalid email address")
        u.email = email or None
    after = {k: getattr(u, k) for k in data}
    if after != before:
        audit.record(
            ctx.db,
            tenant_id=ctx.tenant_id,
            action="user.profile_update",
            actor=u,
            target_type="user",
            target_id=u.id,
            target_name=u.username,
            before=before,
            after=after,
            source_ip=ctx.ip,
        )
    ctx.db.commit()
    return me(ctx)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeIn, ctx: Ctx = Depends(get_ctx)):
    u = ctx.user
    if u.auth_source != "local":
        raise HTTPException(400, "password is managed by the directory / identity provider")
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(400, "current password is incorrect")
    set_password(u, body.new_password)
    audit.record(
        ctx.db,
        tenant_id=u.tenant_id,
        action="user.password_change",
        actor=u,
        target_type="user",
        target_id=u.id,
        target_name=u.username,
        source_ip=ctx.ip,
    )
    ctx.db.commit()


def set_password(user: User, new_password: str) -> None:
    s = get_settings()
    try:
        validate_password_policy(new_password, user.username)
    except PasswordPolicyError as e:
        raise HTTPException(422, str(e)) from e
    previous = [*(user.password_history or []), *([user.password_hash] if user.password_hash else [])]
    if any(verify_password(new_password, h) for h in previous[-s.password_history :]):
        raise HTTPException(422, f"password was used recently (last {s.password_history} are remembered)")
    user.password_history = previous[-s.password_history :]
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()


# --- MFA -----------------------------------------------------------------------


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class OtpIn(BaseModel):
    otp: str


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(ctx: Ctx = Depends(get_ctx)):
    secret = pyotp.random_base32()
    ctx.user.mfa_secret_enc = encrypt_secret(secret)
    ctx.user.mfa_enabled = False
    ctx.db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(ctx.user.username, issuer_name=get_settings().app_name)
    return MfaSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/mfa/verify", status_code=204)
def mfa_verify(body: OtpIn, ctx: Ctx = Depends(get_ctx)):
    secret = decrypt_secret(ctx.user.mfa_secret_enc)
    if not secret or not pyotp.TOTP(secret).verify(body.otp, valid_window=1):
        raise HTTPException(400, "invalid one-time password")
    ctx.user.mfa_enabled = True
    audit.record(
        ctx.db,
        tenant_id=ctx.user.tenant_id,
        action="user.mfa_enabled",
        actor=ctx.user,
        target_type="user",
        target_id=ctx.user.id,
        target_name=ctx.user.username,
        source_ip=ctx.ip,
    )
    ctx.db.commit()


# --- OIDC ----------------------------------------------------------------------


@router.get("/oidc/authorize")
def oidc_authorize(tenant: str | None = None):
    if not get_settings().oidc_enabled:
        raise HTTPException(404, "OIDC not enabled")
    state = secrets.token_urlsafe(24)
    url, verifier = oidc.authorize_url(state)
    oidc.state_store().put(state, {"verifier": verifier, "tenant": tenant}, oidc.STATE_TTL_SECONDS)
    return {"authorization_url": url, "state": state}


@router.get("/oidc/callback", response_model=TokenOut)
def oidc_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.oidc_enabled:
        raise HTTPException(404, "OIDC not enabled")
    pending = oidc.state_store().pop(state)  # one-time use
    if pending is None:
        raise HTTPException(400, "unknown or expired state")
    try:
        tenant = login_svc.resolve_tenant(db, pending.get("tenant"))
    except login_svc.AuthError as e:
        raise HTTPException(400, str(e)) from e
    try:
        claims = oidc.exchange_code(code, pending["verifier"])
    except (httpx.HTTPError, jwt.PyJWTError, KeyError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC code exchange failed") from e
    username = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.external_id == claims["sub"]))
    if user is None:
        clash = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == username))
        if clash is not None:
            # never silently take over an existing (local/LDAP) account by username
            raise HTTPException(409, "username already belongs to a non-SSO account; ask an admin to link it")
        user = User(tenant_id=tenant.id, username=username, auth_source="oidc", external_id=claims["sub"])
        db.add(user)
    elif not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user disabled")
    user.email = claims.get("email") or user.email
    user.full_name = claims.get("name") or user.full_name
    groups = claims.get(s.oidc_groups_claim) or []
    oidc_groups = list(db.scalars(select(Group).where(Group.tenant_id == tenant.id, Group.source == "oidc")))
    user.groups = [g for g in user.groups if g.source != "oidc"] + [g for g in oidc_groups if g.name in groups]
    user.last_login_at = utcnow()
    db.flush()
    login_svc._history(
        db,
        user,
        tenant.id,
        username,
        True,
        "oidc",
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )
    audit.record(db, tenant_id=tenant.id, action="auth.login", actor=user, after={"method": "oidc", "groups": groups})
    pair = login_svc.issue_tokens(db, user)
    db.commit()
    return _tok(pair)


# --- API tokens ----------------------------------------------------------------


class ApiTokenIn(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


class ApiTokenOut(ORM):
    id: uuid.UUID
    name: str
    token_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool
    created_at: datetime


class ApiTokenCreated(ApiTokenOut):
    token: str


@router.get("/tokens", response_model=list[ApiTokenOut])
def list_tokens(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.scalars(
        select(ApiToken).where(ApiToken.user_id == ctx.user.id).order_by(ApiToken.created_at.desc())
    ).all()


@router.post("/tokens", response_model=ApiTokenCreated, status_code=201)
def create_token(body: ApiTokenIn, ctx: Ctx = Depends(get_ctx)):
    bad = set(body.scopes) - ctx.principal.permissions
    if bad:
        raise HTTPException(403, f"cannot delegate permissions you do not hold: {', '.join(sorted(bad))}")
    raw, digest = new_opaque_token("nomt")
    t = ApiToken(
        tenant_id=ctx.user.tenant_id,
        user_id=ctx.user.id,
        name=body.name,
        token_prefix=raw[:12],
        token_hash=digest,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    ctx.db.add(t)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.user.tenant_id,
        action="api_token.create",
        actor=ctx.user,
        target_type="api_token",
        target_id=t.id,
        target_name=t.name,
        after={"scopes": body.scopes},
    )
    ctx.db.commit()
    out = ApiTokenCreated.model_validate({**ApiTokenOut.model_validate(t).model_dump(), "token": raw})
    return out


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    t = ctx.db.get(ApiToken, token_id)
    if t is None or t.user_id != ctx.user.id:
        raise HTTPException(404, "token not found")
    t.revoked = True
    audit.record(
        ctx.db,
        tenant_id=ctx.user.tenant_id,
        action="api_token.revoke",
        actor=ctx.user,
        target_type="api_token",
        target_id=t.id,
        target_name=t.name,
    )
    ctx.db.commit()
