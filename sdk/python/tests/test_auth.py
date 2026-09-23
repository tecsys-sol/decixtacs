from __future__ import annotations

import httpx
import pytest

from networkops import AuthenticationError, MFARequiredError, NetworkOpsClient
from tests.conftest import BASE, FakeClock

ME = {"id": "7f1c6f7e-5a8e-4a52-9b3c-0e7f3f4f2a11", "tenant_id": "3b8f1c1e-8c1e-4d6e-9f1a-2b3c4d5e6f70",
      "username": "alice", "permissions": ["devices:read"], "groups": ["noc"]}


def tokens(n: int, expires_in: int = 900) -> dict:
    return {"access_token": f"acc{n}", "refresh_token": f"ref{n}", "token_type": "bearer", "expires_in": expires_in}


def test_api_token_is_sent_as_bearer(mock, client):
    route = mock.get("/auth/me").respond(json=ME)
    me = client.me()
    assert me.username == "alice" and me.permissions == ["devices:read"]
    assert str(me.id) == ME["id"]
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer nomt_test"
    assert req.headers["user-agent"].startswith("networkops-python/")


def test_password_login_is_lazy_and_sends_tenant_and_otp(mock):
    login = mock.post("/auth/login").respond(json=tokens(1))
    me = mock.get("/auth/me").respond(json=ME)
    c = NetworkOpsClient("https://nom.example.net/", username="alice", password="pw", tenant="acme", otp="123456")
    assert not login.called
    c.me()
    import json

    assert json.loads(login.calls.last.request.content) == {"username": "alice", "password": "pw",
                                                            "tenant": "acme", "otp": "123456"}
    assert me.calls.last.request.headers["authorization"] == "Bearer acc1"


def test_access_token_is_refreshed_before_expiry_and_refresh_token_rotates(mock):
    clock = FakeClock()
    mock.post("/auth/login").respond(json=tokens(1))
    refresh = mock.post("/auth/refresh").mock(side_effect=[httpx.Response(200, json=tokens(2)),
                                                           httpx.Response(200, json=tokens(3))])
    me = mock.get("/auth/me").respond(json=ME)
    c = NetworkOpsClient(BASE, username="alice", password="pw", clock=clock)
    c.me()
    clock.t += 600  # still valid
    c.me()
    assert not refresh.called
    clock.t += 290  # within the 30 s skew window -> refresh first
    c.me()
    assert refresh.call_count == 1
    assert refresh.calls.last.request.content == b'{"refresh_token":"ref1"}'
    assert me.calls.last.request.headers["authorization"] == "Bearer acc2"
    clock.t += 1000
    c.me()
    assert refresh.calls.last.request.content == b'{"refresh_token":"ref2"}'  # rotated token used


def test_failed_refresh_falls_back_to_login(mock):
    clock = FakeClock()
    login = mock.post("/auth/login").mock(side_effect=[httpx.Response(200, json=tokens(1)),
                                                       httpx.Response(200, json=tokens(5))])
    mock.post("/auth/refresh").respond(401, json={"detail": {"code": "token_reuse", "message": "reuse"}})
    me = mock.get("/auth/me").respond(json=ME)
    c = NetworkOpsClient(BASE, username="alice", password="pw", clock=clock)
    c.me()
    clock.t += 5000
    c.me()
    assert login.call_count == 2
    assert me.calls.last.request.headers["authorization"] == "Bearer acc5"


def test_unexpected_401_renews_once_then_raises(mock):
    mock.post("/auth/login").respond(json=tokens(1))
    mock.post("/auth/refresh").respond(json=tokens(2))
    me = mock.get("/auth/me").mock(side_effect=[httpx.Response(401, json={"detail": "invalid or expired token"}),
                                                 httpx.Response(200, json=ME)])
    c = NetworkOpsClient(BASE, username="alice", password="pw")
    assert c.me().username == "alice"
    assert [r.request.headers["authorization"] for r in me.calls] == ["Bearer acc1", "Bearer acc2"]

    mock.get("/auth/me").respond(401, json={"detail": "user disabled"})
    with pytest.raises(AuthenticationError):
        c.me()


def test_api_token_401_is_not_retried(mock, client):
    route = mock.get("/auth/me").respond(401, json={"detail": "invalid API token"})
    with pytest.raises(AuthenticationError) as e:
        client.me()
    assert route.call_count == 1 and e.value.status_code == 401


def test_mfa_required(mock):
    mock.post("/auth/login").respond(401, json={"detail": {"code": "mfa_required",
                                                           "message": "one-time password required"}})
    c = NetworkOpsClient(BASE, username="alice", password="pw")
    with pytest.raises(MFARequiredError) as e:
        c.login()
    assert e.value.code == "mfa_required"


def test_otp_provider_called_per_login(mock):
    login = mock.post("/auth/login").respond(json=tokens(1))
    codes = iter(["111111", "222222"])
    c = NetworkOpsClient(BASE, username="alice", password="pw", otp_provider=lambda: next(codes))
    c.login()
    assert b'"otp":"111111"' in login.calls.last.request.content


def test_close_revokes_refresh_family(mock):
    mock.post("/auth/login").respond(json=tokens(1))
    logout = mock.post("/auth/logout").respond(204)
    c = NetworkOpsClient(BASE, username="alice", password="pw")
    c.login()
    c.close()
    assert logout.calls.last.request.content == b'{"refresh_token":"ref1"}'


def test_credentials_validation():
    with pytest.raises(ValueError):
        NetworkOpsClient(BASE)
    with pytest.raises(ValueError):
        NetworkOpsClient(BASE, token="t", username="u", password="p")


def test_act_as_tenant_header(mock):
    route = mock.get("/auth/me").respond(json=ME)
    NetworkOpsClient(BASE, token="t", act_as_tenant="customer-a").me()
    assert route.calls.last.request.headers["x-tenant"] == "customer-a"
