import pytest

from app.models import IxpMember
from app.services.backup import engine
from app.services.backup.collector import CollectResult
from app.services.dcim import devicetypes, ports

MX_A = """set system host-name mx204-a
set chassis fpc 0 pic 0 port 1 channel-speed 10g
set interfaces et-0/0/0 description "core: to mx204-b et-0/0/0"
set interfaces et-0/0/0 mtu 9192
set interfaces et-0/0/0 unit 0 family inet address 10.1.1.0/31
set interfaces et-0/0/0 unit 0 family iso
set interfaces xe-0/0/1:0 description "channel to customer AS64500"
set interfaces xe-0/0/1:0 unit 0 family inet address 192.0.2.1/30
set interfaces xe-0/1/0 description "IX LAG member"
set interfaces xe-0/1/0 gigether-options 802.3ad ae0
set interfaces xe-0/1/1 gigether-options 802.3ad ae0
set interfaces xe-0/1/2 disable
set interfaces xe-0/1/2 description "spare"
set interfaces ae0 description "Peering LAN"
set interfaces ae0 unit 446 vlan-id 446
set interfaces ae0 unit 446 family inet address 185.1.0.1/24
set interfaces ae0 unit 446 family inet6 address 2001:7f8:1::1/64
set interfaces lo0 unit 0 family inet address 10.255.0.1/32
set interfaces fxp0 unit 0 family inet address 172.17.148.2/24
set protocols isis interface et-0/0/0.0
set protocols bgp group IX neighbor 185.1.0.10 peer-as 13335
set protocols bgp group IX neighbor 185.1.0.11 peer-as 15169
set protocols bgp group CORE neighbor 10.1.1.1 peer-as 65000
"""

MX_B = """set system host-name mx204-b
set interfaces et-0/0/0 description "core: to mx204-a"
set interfaces et-0/0/0 unit 0 family inet address 10.1.1.1/31
"""

IOS = """hostname sw1
interface GigabitEthernet0/0/1
 description uplink to core
 channel-group 10 mode active
!
interface GigabitEthernet0/0/2
 shutdown
!
interface Port-channel10
 description LAG
 ip address 10.0.0.1 255.255.255.252
!
interface GigabitEthernet0/0/3.100
 encapsulation dot1Q 100
 ip address 192.0.2.5 255.255.255.0
 ip ospf 1 area 0
!
interface Vlan10
 ip address 10.10.10.1 255.255.255.0
"""


def test_junos_parser():
    ifs = ports.parse(MX_A, "junos")
    assert ifs["et-0/0/0"].mtu == 9192 and ifs["et-0/0/0"].units["0"].addresses == ["10.1.1.0/31"]
    assert ifs["et-0/0/0"].units["0"].protocols == {"iso", "isis"}
    assert ifs["xe-0/1/0"].lag == "ae0" and ifs["ae0"].is_lag and ifs["xe-0/1/2"].disabled
    assert ifs["ae0"].units["446"].vlan == 446 and len(ifs["ae0"].units["446"].addresses) == 2
    assert ports.is_virtual("lo0") and not ports.is_virtual("xe-0/1/0")


def test_ios_parser():
    ifs = ports.parse(IOS, "ios")
    assert ifs["GigabitEthernet0/0/1"].lag == "Port-channel10" and ifs["GigabitEthernet0/0/2"].disabled
    assert ifs["Port-channel10"].units["0"].addresses == ["10.0.0.1/30"]
    sub = ifs["GigabitEthernet0/0/3"].units["100"]
    assert sub.vlan == 100 and sub.addresses == ["192.0.2.5/24"] and sub.protocols == {"ospf"}
    assert ports.is_virtual("Vlan10")


def test_port_key():
    assert ports.port_key("xe-0/0/1:2") == ports.port_key("et-0/0/1") == "eth:0/0/1"
    assert ports.port_key("Ethernet1/1") == ports.port_key("Et1/1")
    assert ports.port_key("fxp0") == "fxp0"


def test_library_fuzzy_match_and_bundle(monkeypatch, tmp_path):
    cands = {devicetypes.norm(s): s for s in ("QFX5120-48Y-AFI", "QFX5120-48Y-AFO", "QFX5120-48YM-8C", "MX204")}
    assert devicetypes._pick("QFX5120-48Y", cands) == "QFX5120-48Y-AFI"
    assert devicetypes._pick("mx204", cands) == "MX204"
    assert devicetypes._pick("7280CR3-32P4", {"dcs7280cr332p4f": "A"}) == "A"
    assert devicetypes._pick("FortiGate-600F", {"fg600f": "F"}) == "F"
    monkeypatch.setattr(devicetypes.get_settings(), "devicetype_index_url", "")
    monkeypatch.setattr(devicetypes.get_settings(), "devicetype_library_url", "")
    monkeypatch.setattr(devicetypes.get_settings(), "devicetype_cache_dir", str(tmp_path))
    dt = devicetypes.resolve("juniper", "Juniper", "MX204")
    assert dt.source == "bundle" and dt.slug == "juniper-mx204" and len(dt.interfaces) == 13
    assert devicetypes.resolve("juniper", "Juniper", "NO-SUCH-BOX") is None


@pytest.fixture
def offline_library(monkeypatch, tmp_path):
    s = devicetypes.get_settings()
    monkeypatch.setattr(s, "devicetype_index_url", "")
    monkeypatch.setattr(s, "devicetype_library_url", "")
    monkeypatch.setattr(s, "devicetype_cache_dir", str(tmp_path / "dt"))


def test_device_ports_endpoint(admin, db, tenant, monkeypatch, offline_library):
    configs = {"mx204-a": MX_A, "mx204-b": MX_B}

    def collect(targets, workers=50, timeout=60):
        return [CollectResult(t.device_id, True, config=configs[t.hostname], duration_ms=1) for t in targets]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    plat = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    admin.post("/api/v1/credentials", json={"name": "c", "username": "u", "password": "p", "make_default": True})
    ids = {}
    for h, ip in (("mx204-a", "10.0.0.1"), ("mx204-b", "10.0.0.2")):
        ids[h] = admin.post(
            "/api/v1/devices", json={"hostname": h, "management_ip": ip, "platform_id": plat["junos"]}
        ).json()["id"]
    db.add(IxpMember(tenant_id=tenant.id, asn=13335, name="Cloudflare"))
    db.commit()
    assert admin.post("/api/v1/backups/run", json={"run_async": False}).status_code == 200

    # no model known yet -> ports derived from the config
    r = admin.get(f"/api/v1/devices/{ids['mx204-a']}/ports").json()
    assert r["device_type"] is None and r["model"] is None
    assert {p["name"] for p in r["ports"]} >= {"et-0/0/0", "xe-0/1/0", "fxp0"}

    assert admin.put(f"/api/v1/devices/{ids['mx204-a']}/device-type", json={"model": "nope"}).status_code == 422
    ok = admin.put(f"/api/v1/devices/{ids['mx204-a']}/device-type", json={"model": "mx204", "vendor": "juniper"})
    assert ok.status_code == 200 and ok.json()["model"] == "MX204"

    r = admin.get(f"/api/v1/devices/{ids['mx204-a']}/ports").json()
    assert r["device_type"]["slug"] == "juniper-mx204" and r["model_source"] == "override"
    p = {x["name"]: x for x in r["ports"]}
    assert len(r["ports"]) == 13 and p["et-0/0/0"]["form"] == "qsfp" and p["et-0/0/0"]["speed"] == "100G"
    core = p["et-0/0/0"]
    assert core["state"] == "up" and "isis" in core["interfaces"][0]["protocols"]
    peer = next(x for x in core["peers"] if x["source"] == "subnet")
    assert peer["hostname"] == "mx204-b" and peer["interface"] == "et-0/0/0" and peer["address"] == "10.1.1.1"
    # the description names mx204-b too, but the subnet match wins (no duplicate)
    assert len([x for x in core["peers"] if x["kind"] == "device"]) == 1
    ibgp = next(x for x in core["peers"] if x["kind"] == "bgp")
    assert ibgp["asn"] == 65000 and ibgp["hostname"] == "mx204-b"  # the BGP session runs to that device
    # channelised QSFP: xe-0/0/1:0 lives on et-0/0/1
    assert p["et-0/0/1"]["channels"] == ["xe-0/0/1:0"] and p["et-0/0/1"]["peers"][0]["asn"] == 64500
    assert p["xe-0/1/0"]["state"] == "lag" and p["xe-0/1/2"]["state"] == "disabled"
    assert p["xe-0/1/5"]["state"] == "unused" and p["fxp0"]["mgmt"]
    ix = [x for x in p["xe-0/1/0"]["peers"] if x["kind"] == "bgp"]
    assert {x["asn"] for x in ix} == {13335, 15169} and next(x for x in ix if x["asn"] == 13335)["name"] == "Cloudflare"
    assert r["lags"][0]["name"] == "ae0" and r["lags"][0]["members"] == ["xe-0/1/0", "xe-0/1/1"]
    assert any(x["name"] == "lo0" for x in r["logical"])
    assert r["summary"]["ports"] == 13 and r["summary"]["unused"] >= 5

    assert admin.delete(f"/api/v1/devices/{ids['mx204-a']}/device-type").status_code == 204
    assert admin.get(f"/api/v1/devices/{ids['mx204-a']}/front-image").status_code == 404


def test_topology_from_configs(admin, monkeypatch, offline_library):
    third = """set system host-name sw-c
set interfaces xe-0/0/0 description "uplink to mx204-a"
set interfaces xe-0/0/0 gigether-options 802.3ad ae1
set interfaces xe-0/0/1 description "uplink to mx204-a"
set interfaces xe-0/0/1 gigether-options 802.3ad ae1
set interfaces xe-0/0/5 disable
set interfaces xe-0/0/5 description "to mx204-b spare"
"""
    configs = {"mx204-a": MX_A, "mx204-b": MX_B, "sw-c": third}

    def collect(targets, workers=50, timeout=60):
        return [CollectResult(t.device_id, True, config=configs[t.hostname], duration_ms=1) for t in targets]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    plat = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    admin.post("/api/v1/credentials", json={"name": "c", "username": "u", "password": "p", "make_default": True})
    sites = [admin.post("/api/v1/sites", json={"name": n, "slug": n.lower()}).json()["id"] for n in ("FRA", "AMS")]
    ids = {}
    for h, ip, site in (("mx204-a", "10.0.0.1", 0), ("mx204-b", "10.0.0.2", 1), ("sw-c", "10.0.0.3", 0)):
        ids[h] = admin.post(
            "/api/v1/devices",
            json={"hostname": h, "management_ip": ip, "platform_id": plat["junos"], "site_id": sites[site]},
        ).json()["id"]
    admin.post("/api/v1/backups/run", json={"run_async": False})

    t = admin.get("/api/v1/topology").json()
    by = {frozenset((e["source"], e["target"])): e for e in t["edges"]}
    core = by[frozenset((ids["mx204-a"], ids["mx204-b"]))]
    assert core["kind"] == "subnet" and core["detail"] == "10.1.1.0/31" and core["speed_mbps"] == 100_000
    assert core["label"] == "et-0/0/0 - et-0/0/0" and core["status"] == "up"
    lag = by[frozenset((ids["sw-c"], ids["mx204-a"]))]
    assert lag["kind"] == "description" and lag["members"] == 2 and lag["speed_mbps"] == 20_000
    assert "ae1" in lag["label"]
    spare = by[frozenset((ids["sw-c"], ids["mx204-b"]))]
    assert spare["status"] == "down"  # the port naming mx204-b is disabled
    assert {s["name"]: s["device_count"] for s in t["sites"]} == {"FRA": 2, "AMS": 1}

    only_subnets = admin.get("/api/v1/topology", params={"sources": "subnet"}).json()
    assert [e["kind"] for e in only_subnets["edges"]] == ["subnet"]

    # per site: AMS holds mx204-b plus its neighbours elsewhere, flagged external
    ams = admin.get("/api/v1/topology", params={"site_id": sites[1]}).json()
    nodes = {n["label"]: n for n in ams["nodes"]}
    assert not nodes["mx204-b"]["external"] and nodes["mx204-a"]["external"] and nodes["sw-c"]["external"]
    assert len(ams["edges"]) == 2


def test_profile_update(admin):
    me = admin.get("/api/v1/auth/me").json()
    r = admin.patch("/api/v1/auth/me", json={"full_name": "  Shashank K  ", "email": "noc@example.net"})
    assert r.status_code == 200 and r.json()["full_name"] == "Shashank K" and r.json()["email"] == "noc@example.net"
    assert admin.patch("/api/v1/auth/me", json={"email": "nope"}).status_code == 422
    assert admin.get("/api/v1/audit", params={"action": "user.profile_update"}).json()["total"] == 1
    assert me["username"] == admin.get("/api/v1/auth/me").json()["username"]
