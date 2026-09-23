"""Login flows: local / LDAP / OIDC + MFA, lockout, refresh-token rotation with reuse detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decrypt_secret,
    new_opaque_token,
    sha256,
    verify_password,
)
from app.db.base import aware, utcnow
from app.models import Group, LoginHistory, RefreshToken, Tenant, User
from app.services import audit, metrics
from app.services.auth import ldap as ldap_auth


class AuthError(Exception):
    def __init__(self, message: str, code: str = "invalid_credentials"):
        super().__init__(message)
        self.code = code


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _history(
    db: Session,
    user: User | None,
    tenant_id: uuid.UUID,
    username: str,
    ok: bool,
    method: str,
    ip: str | None,
    ua: str | None,
    reason: str | None = None,
) -> None:
    db.add(
        LoginHistory(
            tenant_id=tenant_id,
            user_id=user.id if user else None,
            username=username,
            success=ok,
            method=method,
            source_ip=ip,
            user_agent=(ua or "")[:512],
            reason=reason,
            timestamp=utcnow(),
        )
    )
    if ok:
        metrics.USER_LOGINS.labels(method=method).inc()
    else:
        metrics.LOGIN_FAILURES.labels(source="portal").inc()


def resolve_tenant(db: Session, tenant_slug: str | None) -> Tenant:
    q = select(Tenant).where(Tenant.is_active)
    q = q.where(Tenant.slug == tenant_slug) if tenant_slug else q.order_by(Tenant.created_at)
    tenant = db.scalars(q).first()
    if tenant is None:
        raise AuthError("unknown tenant")
    return tenant


def sync_ldap_groups(db: Session, user: User, group_names: list[str]) -> None:
    """Mirror directory group membership onto platform groups that are sourced from LDAP/AD."""
    groups = list(db.scalars(select(Group).where(Group.tenant_id == user.tenant_id, Group.source.in_(["ldap", "ad"]))))
    wanted = {g.name.lower() for g in groups} & {n.lower() for n in group_names}
    keep = [g for g in user.groups if g.source not in ("ldap", "ad")]
    user.groups = keep + [g for g in groups if g.name.lower() in wanted]


def password_login(
    db: Session,
    tenant_slug: str | None,
    username: str,
    password: str,
    otp: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> TokenPair:
    s = get_settings()
    tenant = resolve_tenant(db, tenant_slug)
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == username))
    now = utcnow()
    if user and user.locked_until and aware(user.locked_until) > now:
        _history(db, user, tenant.id, username, False, "password", ip, ua, "locked")
        db.commit()
        raise AuthError("account temporarily locked", "locked")

    method = "password"
    ok = False
    if user is None or user.auth_source in ("ldap", "ad"):
        if s.ldap_enabled:
            ident = ldap_auth.authenticate(username, password)
            if ident:
                method = "ldap"
                if user is None:  # just-in-time provisioning
                    user = User(tenant_id=tenant.id, username=username, auth_source="ldap", external_id=ident.dn)
                    db.add(user)
                user.email = ident.email or user.email
                user.full_name = ident.full_name or user.full_name
                db.flush()
                sync_ldap_groups(db, user, ident.groups)
                ok = True
    elif user.auth_source == "local":
        ok = verify_password(password, user.password_hash)

    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lockout_minutes)
        _history(db, user, tenant.id, username, False, method, ip, ua, "bad credentials")
        audit.record(
            db, tenant_id=tenant.id, action="auth.login_failed", actor_name=username, source_ip=ip, outcome="failure"
        )
        db.commit()
        raise AuthError("invalid username or password")

    if user.mfa_enabled:
        if not otp:
            raise AuthError("one-time password required", "mfa_required")
        if not pyotp.TOTP(decrypt_secret(user.mfa_secret_enc) or "").verify(otp, valid_window=1):
            user.failed_logins += 1
            _history(db, user, tenant.id, username, False, method, ip, ua, "bad otp")
            db.commit()
            raise AuthError("invalid one-time password", "mfa_invalid")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    _history(db, user, tenant.id, username, True, method, ip, ua)
    audit.record(db, tenant_id=tenant.id, action="auth.login", actor=user, source_ip=ip)
    pair = issue_tokens(db, user)
    db.commit()
    return pair


def issue_tokens(db: Session, user: User, family_id: uuid.UUID | None = None) -> TokenPair:
    s = get_settings()
    raw, digest = new_opaque_token("nomr")
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            family_id=family_id or uuid.uuid4(),
            expires_at=utcnow() + timedelta(days=s.refresh_token_ttl_days),
        )
    )
    access = create_access_token(user.id, user.tenant_id)
    return TokenPair(access, raw, s.access_token_ttl_minutes * 60)


def refresh(db: Session, raw_token: str) -> TokenPair:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(raw_token)))
    now = utcnow()
    if rt is None:
        raise AuthError("invalid refresh token")
    if rt.revoked_at is not None:
        # Reuse of a rotated token => likely theft: revoke the whole family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise AuthError("refresh token reuse detected - session revoked", "token_reuse")
    if aware(rt.expires_at) < now:
        raise AuthError("refresh token expired")
    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise AuthError("user disabled")
    pair = issue_tokens(db, user, rt.family_id)
    rt.revoked_at = now
    rt.replaced_by = db.scalar(select(RefreshToken.id).where(RefreshToken.token_hash == sha256(pair.refresh_token)))
    db.commit()
    return pair


def logout(db: Session, raw_token: str) -> None:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(raw_token)))
    if rt:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        user = db.get(User, rt.user_id)
        if user:
            audit.record(db, tenant_id=user.tenant_id, action="auth.logout", actor=user)
        db.commit()
