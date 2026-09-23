"""OAuth2 / OpenID Connect SSO (authorization code flow with PKCE)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings


@lru_cache
def discovery() -> dict:
    s = get_settings()
    r = httpx.get(f"{s.oidc_issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    return r.json()


def authorize_url(state: str) -> tuple[str, str]:
    """Return (url, code_verifier)."""
    s = get_settings()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "response_type": "code",
        "client_id": s.oidc_client_id,
        "redirect_uri": s.oidc_redirect_uri,
        "scope": "openid profile email groups",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery()['authorization_endpoint']}?{urlencode(params)}", verifier


def exchange_code(code: str, verifier: str) -> dict:
    """Exchange the code and return validated ID-token claims."""
    s = get_settings()
    d = discovery()
    r = httpx.post(
        d["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": s.oidc_redirect_uri,
            "client_id": s.oidc_client_id,
            "client_secret": s.oidc_client_secret,
            "code_verifier": verifier,
        },
        timeout=10,
    )
    r.raise_for_status()
    id_token = r.json()["id_token"]
    return jwt.decode(
        id_token,
        signing_key(d["jwks_uri"], id_token),
        algorithms=["RS256", "ES256", "PS256"],
        audience=s.oidc_client_id,
        issuer=d["issuer"],
    )


def signing_key(jwks_uri: str, id_token: str):
    """Fetch the provider JWKS over httpx (same proxy/CA handling as the rest) and pick the key
    matching the token's ``kid``."""
    r = httpx.get(jwks_uri, timeout=10)
    r.raise_for_status()
    kid = jwt.get_unverified_header(id_token).get("kid")
    keys = [k for k in jwt.PyJWKSet.from_dict(r.json()).keys if kid is None or k.key_id == kid]
    if not keys:
        raise jwt.InvalidTokenError(f"no JWKS key matches kid {kid!r}")
    return keys[0].key


STATE_TTL_SECONDS = 600
_store = None


def state_store():
    """Pending authorisations (state -> PKCE verifier + tenant), shared by all API replicas."""
    global _store
    if _store is None:
        from app.core.redis import EphemeralStore, redis_client

        _store = EphemeralStore("nom:oidc:state:", None if get_settings().environment == "test" else redis_client(0.5))
    return _store
