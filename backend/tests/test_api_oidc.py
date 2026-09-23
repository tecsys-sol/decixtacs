import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.redis import EphemeralStore
from app.services.auth import oidc
from tests.test_unit_redis import FakeRedis

ISSUER = "https://sso.example.net/realms/noc"


@pytest.fixture
def idp(monkeypatch, tenant):
    from app.core.config import get_settings

    s = get_settings()
    for k, v in {
        "oidc_enabled": True,
        "oidc_issuer": ISSUER,
        "oidc_client_id": "nom",
        "oidc_client_secret": "shh",
        "oidc_redirect_uri": "https://nom.example.net/auth/callback",
    }.items():
        monkeypatch.setattr(s, k, v)
    oidc.discovery.cache_clear()
    store = EphemeralStore("nom:oidc:state:", FakeRedis())
    monkeypatch.setattr(oidc, "_store", store)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    state = {"claims": {}, "verifier": None}

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                },
            )
        )
        mock.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
            return_value=httpx.Response(200, json={"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]})
        )

        def token(request):
            form = parse_qs(request.content.decode())
            state["verifier"] = form["code_verifier"][0]
            assert form["code"] == ["the-code"] and form["client_secret"] == ["shh"]
            now = int(time.time())
            claims = {"iss": ISSUER, "aud": "nom", "iat": now, "exp": now + 300, **state["claims"]}
            return httpx.Response(
                200, json={"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})}
            )

        mock.post(f"{ISSUER}/protocol/openid-connect/token").mock(side_effect=token)
        yield {"store": store, "state": state}
    oidc.discovery.cache_clear()


def _authorize(client, tenant="decix"):
    r = client.get("/api/v1/auth/oidc/authorize", params={"tenant": tenant})
    assert r.status_code == 200, r.text
    body = r.json()
    q = parse_qs(urlsplit(body["authorization_url"]).query)
    assert q["state"] == [body["state"]] and q["code_challenge_method"] == ["S256"]
    return body["state"], q["code_challenge"][0]


def test_oidc_end_to_end_jit_user_and_group_mapping(admin, client, idp):
    admin.post("/api/v1/groups", json={"name": "noc-engineers", "source": "oidc"})
    admin.post("/api/v1/groups", json={"name": "local-only", "source": "local"})
    state, challenge = _authorize(client)
    assert idp["store"].client.ttl[f"nom:oidc:state:{state}"] == 600  # stored in Redis with a TTL
    idp["state"]["claims"] = {
        "sub": "idp-123",
        "preferred_username": "jdoe",
        "email": "jdoe@example.net",
        "name": "Jane Doe",
        "groups": ["noc-engineers", "local-only", "unknown"],
    }
    r = client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state})
    assert r.status_code == 200, r.text
    # PKCE: the verifier sent to the token endpoint matches the challenge sent to the browser
    digest = base64.urlsafe_b64encode(hashlib.sha256(idp["state"]["verifier"].encode()).digest()).rstrip(b"=")
    assert digest.decode() == challenge
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["username"] == "jdoe" and me["auth_source"] == "oidc" and me["full_name"] == "Jane Doe"
    assert me["groups"] == ["noc-engineers"]  # only oidc-sourced groups are mapped
    # state is one-time use
    again = client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state})
    assert again.status_code == 400
    # second login: same user (matched on sub), groups re-synced
    state, _ = _authorize(client)
    idp["state"]["claims"]["groups"] = []
    r = client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state})
    tok = r.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["groups"] == []
    users = admin.get("/api/v1/users", params={"q": "jdoe"}).json()
    assert users["total"] == 1
    assert admin.get("/api/v1/login-history", params={"username": "jdoe"}).json()["total"] == 2


def test_oidc_refuses_takeover_disabled_and_bad_state(admin, client, idp):
    assert client.get("/api/v1/auth/oidc/callback", params={"code": "x", "state": "forged"}).status_code == 400
    state, _ = _authorize(client)
    idp["state"]["claims"] = {"sub": "idp-9", "preferred_username": "admin"}  # clashes with local admin
    assert client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state}).status_code == 409
    idp["state"]["claims"] = {"sub": "idp-10", "preferred_username": "mallory"}
    state, _ = _authorize(client)
    assert client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state}).status_code == 200
    uid = admin.get("/api/v1/users", params={"q": "mallory"}).json()["items"][0]["id"]
    admin.patch(f"/api/v1/users/{uid}", json={"is_active": False})
    state, _ = _authorize(client)
    assert client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state}).status_code == 401


def test_oidc_bad_signature_rejected(client, idp, monkeypatch):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    real_encode = jwt.encode
    monkeypatch.setattr(jwt, "encode", lambda claims, key, **kw: real_encode(claims, other, **kw))
    state, _ = _authorize(client)
    idp["state"]["claims"] = {"sub": "idp-11", "preferred_username": "eve"}
    assert client.get("/api/v1/auth/oidc/callback", params={"code": "the-code", "state": state}).status_code == 401
