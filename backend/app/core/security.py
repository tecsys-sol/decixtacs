"""Password hashing, password policy, JWT issuance and secret encryption."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


class PasswordPolicyError(ValueError):
    pass


def validate_password_policy(password: str, username: str | None = None) -> None:
    s = get_settings()
    problems: list[str] = []
    if len(password) < s.password_min_length:
        problems.append(f"must be at least {s.password_min_length} characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]"))
    if classes < s.password_require_classes:
        problems.append(f"must contain at least {s.password_require_classes} character classes")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if problems:
        raise PasswordPolicyError("Password " + "; ".join(problems))


# --- JWT -------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID | None, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_ttl_minutes),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_opaque_token(prefix: str) -> tuple[str, str]:
    """Return (plaintext, sha256) for refresh / API tokens. Only the hash is stored."""
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, sha256(raw)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- Secret encryption (device credentials, TACACS keys, integration tokens) --


def _fernet() -> MultiFernet:
    s = get_settings()
    keys = [k.strip() for k in s.encryption_keys.split(",") if k.strip()]
    if not keys:
        if s.environment == "production":
            raise RuntimeError("NOM_ENCRYPTION_KEYS must be set in production")
        # Deterministic development key derived from the JWT secret.
        import base64

        keys = [base64.urlsafe_b64encode(hashlib.sha256(s.jwt_secret.encode()).digest()).decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_secret(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt secret - wrong or rotated-out key") from exc


def rotate_secret(ciphertext: str) -> str:
    """Re-encrypt a secret with the newest key (MultiFernet.rotate)."""
    return _fernet().rotate(ciphertext.encode()).decode()
