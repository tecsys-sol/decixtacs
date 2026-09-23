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
    key = jwt.PyJWKClient(d["jwks_uri"]).get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token, key.key, algorithms=["RS256", "ES256", "PS256"], audience=s.oidc_client_id, issuer=d["issuer"]
    )
