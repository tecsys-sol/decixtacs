from app.services.bootstrap import create_tenant
from tests.conftest import ADMIN_PW, as_user


def _other_tenant(db):
    t = create_tenant(db, "Other ISP", "other", "admin", ADMIN_PW)
    db.commit()
    return t


def test_tenant_isolation(admin, client, db):
    d = admin.post("/api/v1/devices", json={"hostname": "mx204-blr", "management_ip": "10.0.0.1"}).json()
    _other_tenant(db)
    other = as_user(client, "admin", ADMIN_PW, tenant="other")
    assert other.get("/api/v1/devices").json()["total"] == 0
    assert other.get(f"/api/v1/devices/{d['id']}").status_code == 404
    assert other.patch(f"/api/v1/devices/{d['id']}", json={"role": "x"}).status_code == 404
    # X-Tenant header requires superuser
    other.headers["X-Tenant"] = "decix"
    assert other.get("/api/v1/devices").status_code == 403


def test_superuser_can_switch_tenant(client, db):
    t = create_tenant(db, "MSP Ops", "msp", "operator", ADMIN_PW, superuser=True)
    _other_tenant(db)
    db.commit()
    op = as_user(client, "operator", ADMIN_PW, tenant="msp")
    assert {x["slug"] for x in op.get("/api/v1/tenants").json()} == {"msp", "other"}
    op.headers["X-Tenant"] = "other"
    assert op.post("/api/v1/devices", json={"hostname": "r1", "management_ip": "10.1.1.1"}).status_code == 201
    other = as_user(client, "admin", ADMIN_PW, tenant="other")
    assert other.get("/api/v1/devices").json()["total"] == 1
    r = op.post("/api/v1/tenants", json={"name": "New", "slug": "new", "admin_password": ADMIN_PW})
    assert r.status_code == 201
    assert t.id


def test_abac_site_scoped_binding(admin, client):
    s1 = admin.post("/api/v1/sites", json={"name": "Bangalore", "slug": "blr"}).json()
    s2 = admin.post("/api/v1/sites", json={"name": "Mumbai", "slug": "bom"}).json()
    admin.post("/api/v1/devices", json={"hostname": "blr-r1", "management_ip": "10.0.0.1", "site_id": s1["id"]})
    d2 = admin.post(
        "/api/v1/devices", json={"hostname": "bom-r1", "management_ip": "10.0.0.2", "site_id": s2["id"]}
    ).json()
    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    u = admin.post("/api/v1/users", json={"username": "blr-eng", "password": "Bangal0re-Eng!x"}).json()
    r = admin.post(
        "/api/v1/role-bindings",
        json={"role_id": roles["network-engineer"], "user_id": u["id"], "scope_type": "site", "scope_id": s1["id"]},
    )
    assert r.status_code == 201
    c = as_user(client, "blr-eng", "Bangal0re-Eng!x")
    names = [d["hostname"] for d in c.get("/api/v1/devices").json()["items"]]
    assert names == ["blr-r1"]
    assert c.get(f"/api/v1/devices/{d2['id']}").status_code == 404
    assert c.patch(f"/api/v1/devices/{d2['id']}", json={"role": "core"}).status_code == 403


def test_cannot_escalate_privileges(admin, client):
    roles = {r["name"]: r["id"] for r in admin.get("/api/v1/roles").json()}
    u = admin.post("/api/v1/users", json={"username": "ua", "password": "User-Admin-Pass1"}).json()
    admin.post("/api/v1/roles", json={"name": "user-admin", "permissions": ["users:read", "users:write"]})
    ua_role = [r for r in admin.get("/api/v1/roles").json() if r["name"] == "user-admin"][0]
    admin.post("/api/v1/role-bindings", json={"role_id": ua_role["id"], "user_id": u["id"]})
    c = as_user(client, "ua", "User-Admin-Pass1")
    r = c.post("/api/v1/role-bindings", json={"role_id": roles["admin"], "user_id": u["id"]})
    assert r.status_code == 403
