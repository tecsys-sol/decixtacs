import io
import tarfile

from app.services import rancid as rs
from tests.test_api_configs import _backup, _device, fake_collector  # noqa: F401

CLOGINRC = r"""
# rancid .cloginrc
add user        fw-*            {fwadmin}
add password    fw-*            {Fw-Pass-1} {Fw-Enable-1}
add identity    lab-*           /home/rancid/.ssh/id_lab
add method      *               ssh
add user        *               rancid
add password    *.theixp.net    {Rancid-Pass-9}
add password    10.0.0.*        {Rancid-Pass-9}
add password    *               {Rancid-Pass-9} {En-9}
add noenable    blr-*           1
include /home/rancid/.cloginrc.extra
"""

ROUTER_DB = """
# group: ixp
blr-01-ixp01.theixp.net;juniper;up
blr-02-ixp02;juniper;up
fw-edge;fortigate;up
sw-old;cisco;down
ghost-router;juniper;up
"""

JUNOS_HIER = """# RANCID-CONTENT-TYPE: juniper
# Chassis                                MX204
version 21.4R3;
system {
    host-name mx204-blr;
    ntp {
        server 10.0.0.10;
    }
    syslog {
        host 10.0.0.20 {
            any notice;
        }
    }
}
snmp {
    community public {
        authorization read-only;
    }
}
protocols {
    bgp {
        group TRANSIT {
            neighbor 10.0.0.2 {
                peer-as 13335;
            }
        }
    }
}
policy-options {
    community IX members [ 65000:100 65000:200 ];
}
inactive: interfaces {
    ae0 {
        description "core uplink";
    }
}
"""


def test_cloginrc_parsing_and_first_match_wins():
    d, warnings = rs.parse_cloginrc(CLOGINRC)
    assert any("include" in w for w in warnings)
    fw = rs.login_for(d, ["fw-edge"])
    assert (fw.username, fw.password, fw.enable) == ("fwadmin", "Fw-Pass-1", "Fw-Enable-1")
    blr = rs.login_for(d, ["blr-01-ixp01.theixp.net"])
    assert (blr.username, blr.password, blr.enable) == ("rancid", "Rancid-Pass-9", None)  # noenable
    core = rs.login_for(d, ["core1"])
    assert core.enable == "En-9"
    assert rs.login_for(d, ["lab-1"]).password == "Rancid-Pass-9" and rs.login_for(d, ["lab-1"]).identity
    assert rs._tcl_words('add password x {a b} "c d" e') == ["add", "password", "x", "a b", "c d", "e"]


def test_junos_hierarchical_to_set():
    lines = rs.junos_to_set(JUNOS_HIER)
    assert "set version 21.4R3" in lines
    assert "set system syslog host 10.0.0.20 any notice" in lines
    assert "set policy-options community IX members 65000:100" in lines
    assert "set policy-options community IX members 65000:200" in lines
    assert 'set interfaces ae0 description "core uplink"' in lines
    assert "deactivate interfaces" in lines


def test_import_credentials_from_rancid(admin):
    platforms = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    hosts = (
        ("BLR-01-IXP01", "172.17.148.2"),
        ("BLR-02-IXP02", "172.17.148.3"),
        ("fw-edge", "10.9.9.1"),
        ("sw-old", "10.0.0.7"),
    )
    for host, ip in hosts:
        admin.post("/api/v1/devices", json={"hostname": host, "management_ip": ip})
    admin.post(
        "/api/v1/devices", json={"hostname": "core1", "management_ip": "10.0.0.1", "platform_id": platforms["ios"]}
    )
    body = {"cloginrc": CLOGINRC, "router_db": ROUTER_DB}
    dry = admin.post("/api/v1/rancid/import-credentials", json=body).json()
    assert dry["dry_run"] and admin.get("/api/v1/credentials").json() == []
    creds = {c["name"]: c for c in dry["credentials"]}
    # the most common login (no enable on blr-*) becomes the default
    assert creds["rancid-rancid"]["is_default"] and creds["rancid-rancid"]["devices"] == [
        "BLR-01-IXP01",
        "BLR-02-IXP02",
    ]
    assert creds["rancid-rancid-2"]["has_enable_secret"] and creds["rancid-rancid-2"]["devices"] == ["sw-old"]
    assert creds["rancid-fwadmin"]["has_enable_secret"] and creds["rancid-fwadmin"]["devices"] == ["fw-edge"]
    assert dry["router_db_not_in_inventory"] == ["ghost-router"] and dry["router_db_down"] == ["sw-old (down)"]
    assert "BLR-01-IXP01 → junos" in dry["platforms_set"] and "fw-edge → fortios" in dry["platforms_set"]

    real = admin.post("/api/v1/rancid/import-credentials", json={**body, "dry_run": False}).json()
    stored = {c["name"]: c for c in admin.get("/api/v1/credentials").json()}
    assert stored["rancid-rancid"]["is_default"] and stored["rancid-fwadmin"]["device_count"] == 1
    assert stored["rancid-rancid-2"]["device_count"] == 1
    devs = {d["hostname"]: d for d in admin.get("/api/v1/devices", params={"limit": 50}).json()["items"]}
    assert devs["BLR-01-IXP01"]["platform"]["slug"] == "junos"
    assert real["assigned"] == 2  # fw-edge and sw-old; the BLR routers use the default
    # re-running reuses the identical credentials
    again = admin.post("/api/v1/rancid/import-credentials", json={**body, "dry_run": False}).json()
    assert all(c["existing"] for c in again["credentials"]) and len(admin.get("/api/v1/credentials").json()) == 3
    assert admin.get("/api/v1/audit", params={"action": "credential.import_rancid"}).json()["total"] == 2


def _archive(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_compare_rancid_configs_with_backups(admin, fake_collector):  # noqa: F811
    _device(admin)  # mx204-blr, junos; backup content = tests.test_api_configs.CONFIGS[1]
    _backup(admin)
    other = JUNOS_HIER.replace("        server 10.0.0.10;\n", "        server 10.0.0.99;\n")
    arc = _archive(
        {
            "./ixp/configs/mx204-blr": other,
            "./ixp/configs/unknown-sw": "hostname unknown-sw\n",
            "./ixp/router.db": "mx204-blr;juniper;up\n",
            "./ixp/configs/CVS/Entries": "x",
        }
    )
    r = admin.post("/api/v1/rancid/configs", files={"file": ("rancid.tgz", arc, "application/gzip")}).json()
    assert r == {"files": 2, "matched": 1, "unmatched": ["unknown-sw"]}
    rows = {x["rancid_name"]: x for x in admin.get("/api/v1/rancid/compare").json()}
    mx = rows["mx204-blr"]
    assert mx["status"] == "differs" and mx["hostname"] == "mx204-blr" and mx["similarity"] > 50
    assert rows["unknown-sw"]["status"] == "not_in_inventory"
    d = admin.get(f"/api/v1/rancid/compare/{mx['id']}").json()
    assert d["junos_converted"]
    left = {x["left"] for x in d["side_by_side"] if x["type"] in ("removed", "modified")}
    assert "set system ntp server 10.0.0.99" in left
    assert (
        admin.post("/api/v1/rancid/configs", files={"file": ("x.tgz", b"nope", "application/gzip")}).status_code == 422
    )
    assert admin.delete("/api/v1/rancid/configs").status_code == 204
    assert admin.get("/api/v1/rancid/compare").json() == []
