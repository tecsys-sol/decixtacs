import pyotp

from tests.conftest import ADMIN_PW, as_user, login


def test_login_me_and_refresh_rotation(client, tenant):
    tok = login(client)
    client.headers["Authorization"] = f"Bearer {tok['access_token']}"
    me = client.get("/api/v1/auth/me").json()
    assert (
        me["username"] == "admin" and "tacacs:write" in me["permissions"] and "tenants:admin" not in me["permissions"]
    )

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    # re-using the rotated token revokes the whole family
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "token_reuse"
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_bad_password_lockout(client, tenant):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope", "tenant": "decix"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW, "tenant": "decix"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "locked"


def test_unauthenticated_rejected(client, tenant):
    assert client.get("/api/v1/devices").status_code == 401
    client.headers["Authorization"] = "Bearer garbage"
    assert client.get("/api/v1/devices").status_code == 401


def test_mfa_enrolment_and_login(admin):
    setup = admin.post("/api/v1/auth/mfa/setup").json()
    totp = pyotp.TOTP(setup["secret"])
    assert admin.post("/api/v1/auth/mfa/verify", json={"otp": "000000"}).status_code == 400
    assert admin.post("/api/v1/auth/mfa/verify", json={"otp": totp.now()}).status_code == 204
    r = admin.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW, "tenant": "decix"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "mfa_required"
    assert login(admin, otp=totp.now())["access_token"]


def test_password_policy_and_history(admin):
    r = admin.post("/api/v1/users", json={"username": "weak", "password": "short"})
    assert r.status_code == 422
    r = admin.post("/api/v1/auth/password", json={"current_password": ADMIN_PW, "new_password": ADMIN_PW})
    assert r.status_code == 422 and "used recently" in r.text
    r = admin.post("/api/v1/auth/password", json={"current_password": ADMIN_PW, "new_password": "An0ther-Str0ng-Pass"})
    assert r.status_code == 204


def test_api_token_scopes(admin, client):
    r = admin.post("/api/v1/auth/tokens", json={"name": "ci", "scopes": ["devices:read"]})
    assert r.status_code == 201
    raw = r.json()["token"]
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {raw}"
    assert c.get("/api/v1/devices").status_code == 200
    assert c.get("/api/v1/users").status_code == 403  # admin has users:read, the token does not
    admin.delete(f"/api/v1/auth/tokens/{r.json()['id']}")
    assert c.get("/api/v1/devices").status_code == 401


def test_rate_limit_headers(admin):
    r = admin.get("/api/v1/devices")
    assert "X-RateLimit-Remaining" in r.headers and r.headers["X-Content-Type-Options"] == "nosniff"


def test_readonly_user_forbidden_to_write(admin, client):
    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    u = admin.post("/api/v1/users", json={"username": "noc1", "password": "Noc-User-Pass-1"}).json()
    admin.post("/api/v1/role-bindings", json={"role_id": roles["read-only"], "user_id": u["id"]})
    c = as_user(client, "noc1", "Noc-User-Pass-1")
    assert c.get("/api/v1/devices").status_code == 200
    assert c.post("/api/v1/devices", json={"hostname": "x", "management_ip": "1.1.1.1"}).status_code == 403
    assert c.get("/api/v1/audit").status_code == 403
