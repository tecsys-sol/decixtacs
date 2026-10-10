import json

from app.services.backup import engine
from app.services.backup.collector import CollectResult
from app.services.dcim import neighbors
from tests.test_dcim import offline_library  # noqa: F401


def _junos_json(rows: list[dict]) -> str:
    def d(v):
        return [{"data": v}]

    items = []
    for r in rows:
        item = {"lldp-local-port-id": d(r["local"]), "lldp-remote-system-name": d(r["system"])}
        if r.get("parent"):
            item["lldp-local-parent-interface-name"] = d(r["parent"])
        if r.get("port"):
            item["lldp-remote-port-id"] = d(r["port"])
        if r.get("port_desc"):
            item["lldp-remote-port-description"] = d(r["port_desc"])
        items.append(item)
    body = json.dumps({"lldp-neighbors-information": [{"lldp-neighbor-information": items}]})
    return "{master:0}\nadmin@box> show lldp neighbors | display json | no-more\n" + body + "\n\n{master:0}\n"


def test_junos_json_and_text():
    out = neighbors.parse(
        _junos_json([{"local": "et-0/0/0", "parent": "ae0", "system": "b", "port": "et-0/0/1"}]), "junos"
    )
    assert [(n.local_interface, n.remote_system, n.remote_port) for n in out] == [("et-0/0/0", "b", "et-0/0/1")]
    text = """Local Interface    Parent Interface    Chassis Id          Port info          System Name
et-0/0/0           ae0                 2c:6b:f5:00:00:01   et-0/0/1           del-02-ixp02
xe-0/0/5           -                   00:11:22:33:44:55   Gi0/0/1            cust-rtr
"""
    out = neighbors.parse(text, "junos")
    assert [(n.local_interface, n.remote_system, n.remote_port, n.remote_chassis) for n in out] == [
        ("et-0/0/0", "del-02-ixp02", "et-0/0/1", "2c:6b:f5:00:00:01"),
        ("xe-0/0/5", "cust-rtr", "Gi0/0/1", "00:11:22:33:44:55"),
    ]


def test_eos_nxos_ios_routeros():
    eos = json.dumps(
        {
            "lldpNeighbors": [
                {"port": "Ethernet1", "neighborDevice": "mx-a.example", "neighborPort": "xe-0/0/1", "ttl": 120}
            ]
        }
    )
    assert [(n.local_interface, n.remote_system, n.remote_port) for n in neighbors.parse(eos, "eos")] == [
        ("Ethernet1", "mx-a.example", "xe-0/0/1")
    ]
    eos_detail = json.dumps(
        {
            "lldpNeighbors": {
                "Ethernet2": {
                    "lldpNeighborInfo": [
                        {
                            "systemName": "sw9",
                            "chassisId": "aa",
                            "neighborInterfaceInfo": {"interfaceId_v2": "Ethernet5", "interfaceDescription": "to x"},
                            "managementAddresses": [{"address": "10.9.9.9"}],
                        }
                    ]
                }
            }
        }
    )
    n = neighbors.parse(eos_detail, "eos")[0]
    assert (n.local_interface, n.remote_system, n.remote_port, n.remote_address) == (
        "Ethernet2",
        "sw9",
        "Ethernet5",
        "10.9.9.9",
    )
    nxos = json.dumps(
        {
            "TABLE_nbor_detail": {
                "ROW_nbor_detail": {
                    "l_port_id": "Eth1/1",
                    "sys_name": "core1",
                    "port_id": "Ethernet1/49",
                    "mgmt_addr": "10.0.0.9",
                }
            }
        }
    )
    n = neighbors.parse(nxos, "nxos")[0]
    assert (n.local_interface, n.remote_system, n.remote_port, n.remote_address) == (
        "Eth1/1",
        "core1",
        "Ethernet1/49",
        "10.0.0.9",
    )
    ios = """
Capability codes:
------------------------------------------------
Local Intf: Gi0/0/0
Chassis id: 2c6b.f500.0001
Port id: xe-0/0/3
Port Description: core: to isr
System Name: mx204-blr1-core

Management Addresses:
    IP: 10.10.0.3
------------------------------------------------
Local Intf: Te0/1/0
Chassis id: 0011.2233.4455
Port id: Ethernet7
System Name: 7280r3-sin1-peer1

Total entries displayed: 2
"""
    got = [(n.local_interface, n.remote_system, n.remote_port, n.remote_address) for n in neighbors.parse(ios, "ios")]
    assert got == [
        ("Gi0/0/0", "mx204-blr1-core", "xe-0/0/3", "10.10.0.3"),
        ("Te0/1/0", "7280r3-sin1-peer1", "Ethernet7", None),
    ]
    ros = ' 0 interface=ether1-uplink address=10.30.0.0 mac-address=2C:6B:F5:00:00:09 identity="blr-01-ixp01" platform=Juniper interface-name=et-0/0/7 discovered-by=lldp\n'
    n = neighbors.parse(ros, "routeros")[0]
    assert (n.local_interface, n.remote_system, n.remote_port) == ("ether1-uplink", "blr-01-ixp01", "et-0/0/7")
    assert neighbors.parse("garbage", "junos") == [] and neighbors.parse("x", "fortios") == []


IXP_A = """set system host-name ixp-a
set interfaces et-0/0/0 ether-options 802.3ad ae0
set interfaces et-0/0/1 ether-options 802.3ad ae0
set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
set interfaces xe-0/0/5 description "CUST-0042"
set interfaces xe-0/0/6 unit 0 family inet address 10.9.0.0/31
"""
IXP_B = """set system host-name ixp-b
set interfaces et-0/0/2 ether-options 802.3ad ae3
set interfaces et-0/0/3 ether-options 802.3ad ae3
set interfaces ae3 unit 0 family ethernet-switching interface-mode trunk
"""
RTR_C = """set system host-name rtr-c
set interfaces xe-1/0/0 unit 0 family inet address 10.9.0.1/31
"""


def test_lldp_links_on_the_map_and_ports(admin, monkeypatch, offline_library):  # noqa: F811
    configs = {"ixp-a": IXP_A, "ixp-b": IXP_B, "rtr-c": RTR_C}
    lldp = {
        # ixp-a reports ifIndex numbers as far ports for the fabric, names for the rest
        "ixp-a": _junos_json(
            [
                {
                    "local": "et-0/0/0",
                    "parent": "ae0",
                    "system": "ixp-b.example.net",
                    "port": "531",
                    "port_desc": "et-0/0/2",
                },
                {"local": "et-0/0/1", "parent": "ae0", "system": "ixp-b.example.net", "port": "532"},
                {"local": "xe-0/0/5", "system": "cust-rtr-42", "port": "TenGigE0/0/0/1"},
                {"local": "xe-0/0/6", "system": "rtr-c", "port": "xe-1/0/0"},
            ]
        ),
        "ixp-b": _junos_json(
            [
                {"local": "et-0/0/2", "parent": "ae3", "system": "IXP-A", "port": "et-0/0/0"},
                {"local": "et-0/0/3", "parent": "ae3", "system": "IXP-A", "port": "et-0/0/1"},
            ]
        ),
        "rtr-c": "",  # LLDP off
    }
    seen_targets = []

    def collect(targets, workers=50, timeout=60):
        seen_targets.extend(targets)
        return [
            CollectResult(t.device_id, True, config=configs[t.hostname], duration_ms=1, neighbors=lldp[t.hostname])
            for t in targets
        ]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    plat = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    admin.post("/api/v1/credentials", json={"name": "c", "username": "u", "password": "p", "make_default": True})
    site = admin.post("/api/v1/sites", json={"name": "DEL", "slug": "del"}).json()["id"]
    ids = {}
    for n, h in enumerate(configs):
        ids[h] = admin.post(
            "/api/v1/devices",
            json={"hostname": h, "management_ip": f"10.0.9.{n + 1}", "platform_id": plat["junos"], "site_id": site},
        ).json()["id"]
    admin.post("/api/v1/backups/run", json={"run_async": False})
    assert all(t.neighbor_commands == ["show lldp neighbors | display json | no-more"] for t in seen_targets)

    t = admin.get("/api/v1/topology").json()
    by = {frozenset((e["source"], e["target"])): e for e in t["edges"]}
    fabric = by[frozenset((ids["ixp-a"], ids["ixp-b"]))]
    # an L2 LAG with no addresses or descriptions: only LLDP knows it; both ends' members fold into one link
    assert fabric["kind"] == "lldp" and fabric["members"] == 2 and fabric["speed_mbps"] == 200_000
    assert {fabric["a_interface"], fabric["b_interface"]} == {"ae0", "ae3"}
    routed = by[frozenset((ids["ixp-a"], ids["rtr-c"]))]
    assert routed["kind"] == "lldp" and routed["detail"] == "10.9.0.0/31"  # the subnet annotates the LLDP link
    assert len([e for e in t["edges"] if not e.get("customer")]) == 2

    no_lldp = admin.get("/api/v1/topology", params={"sources": "subnet,description"}).json()
    assert [e["kind"] for e in no_lldp["edges"] if not e.get("customer")] == ["subnet"]

    ports = admin.get(f"/api/v1/devices/{ids['ixp-a']}/ports").json()
    allp = {i["name"]: i for p in ports["ports"] + ports["unmatched"] for i in p.get("interfaces", [p])}
    cust = [p for p in allp["xe-0/0/5"]["peers"] if p["source"] == "lldp"]
    assert cust == [
        {
            "kind": "lldp",
            "source": "lldp",
            "name": "cust-rtr-42",
            "interface": "TenGigE0/0/0/1",
            "address": None,
            "chassis": None,
        }
    ]
    member = allp["et-0/0/0"]
    assert any(
        p.get("hostname") == "ixp-b" and p["source"] == "lldp" for p in member["peers"] + member.get("lag_peers", [])
    )

    # ixp-b's own view stays even when LLDP stops answering: a failed command keeps nothing stale
    lldp["ixp-b"] = ""
    admin.post("/api/v1/backups/run", json={"run_async": False})
    fabric = {frozenset((e["source"], e["target"])): e for e in admin.get("/api/v1/topology").json()["edges"]}[
        frozenset((ids["ixp-a"], ids["ixp-b"]))
    ]
    assert fabric["kind"] == "lldp" and fabric["members"] == 2  # ixp-a still sees it


RANCID_ONLY = """# RANCID-CONTENT-TYPE: juniper
# Chassis                                MX204
version 21.4R3;
interfaces {
    et-0/0/4 {
        description "core: to TO_IXP-A";
        unit 0 {
            family inet {
                address 10.9.1.1/31;
            }
        }
    }
}
"""


def test_devices_without_nom_backup_use_rancid_configs(admin, monkeypatch, offline_library):  # noqa: F811
    from tests.test_rancid import _archive

    cfg_a = IXP_A + "set interfaces et-0/0/4 unit 0 family inet address 10.9.1.0/31\n"

    def collect(targets, workers=50, timeout=60):
        return [CollectResult(t.device_id, True, config=cfg_a, duration_ms=1) for t in targets]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    plat = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    admin.post("/api/v1/credentials", json={"name": "c", "username": "u", "password": "p", "make_default": True})
    site = admin.post("/api/v1/sites", json={"name": "DEL", "slug": "del"}).json()["id"]
    a = admin.post(
        "/api/v1/devices",
        json={"hostname": "ixp-a", "management_ip": "10.0.9.1", "platform_id": plat["junos"], "site_id": site},
    ).json()["id"]
    admin.post("/api/v1/backups/run", json={"run_async": False, "device_ids": [a]})
    # no credential reachable for this one: only RANCID has its config
    d = admin.post(
        "/api/v1/devices",
        json={"hostname": "DEL-04-RTR01", "management_ip": "10.0.9.4", "platform_id": plat["junos"], "site_id": site},
    ).json()["id"]
    assert admin.get(f"/api/v1/devices/{d}/ports").json()["has_config"] is False
    arc = _archive({"./del/configs/del-04-rtr01.del.int.theixp.net": RANCID_ONLY})
    assert (
        admin.post("/api/v1/rancid/configs", files={"file": ("r.tgz", arc, "application/gzip")}).json()["matched"] == 1
    )

    ports = admin.get(f"/api/v1/devices/{d}/ports").json()
    assert ports["has_config"] and ports["config_source"] == "rancid_upload"
    names = {i["name"] for p in ports["ports"] + ports["unmatched"] for i in p.get("interfaces", [p])}
    assert "et-0/0/4" in names
    edges = admin.get("/api/v1/topology").json()["edges"]
    link = next(e for e in edges if {e["source"], e["target"]} == {a, d})
    assert link["kind"] == "subnet" and link["detail"] == "10.9.1.0/31"


def test_neighbor_commands_in_backup_settings(admin):
    junos = next(p for p in admin.get("/api/v1/backup-settings").json()["platforms"] if p["slug"] == "junos")
    assert junos["default_neighbor_commands"] == ["show lldp neighbors | display json | no-more"]
    assert junos["neighbor_commands"] is None
    off = admin.put("/api/v1/backup-settings/junos", json={"neighbor_commands": []}).json()
    assert next(p for p in off["platforms"] if p["slug"] == "junos")["neighbor_commands"] == []
    custom = admin.put(
        "/api/v1/backup-settings/junos", json={"neighbor_commands": [" show lldp neighbors ", ""]}
    ).json()
    assert next(p for p in custom["platforms"] if p["slug"] == "junos")["neighbor_commands"] == ["show lldp neighbors"]
    reset = admin.put("/api/v1/backup-settings/junos", json={}).json()
    assert next(p for p in reset["platforms"] if p["slug"] == "junos")["neighbor_commands"] is None


def test_customer_routers_on_the_map(admin, db, tenant, monkeypatch, offline_library):  # noqa: F811
    from app.models import IxpMember

    sw = (
        IXP_A
        + 'set interfaces xe-0/0/7 description "AS13335_Cloudflare 100G"\nset interfaces xe-0/0/8 description "spare"\n'
    )
    configs = {"ixp-a": sw, "ixp-b": IXP_B}
    lldp = {
        "ixp-a": _junos_json(
            [
                {"local": "et-0/0/0", "parent": "ae0", "system": "ixp-b", "port": "et-0/0/2"},
                {"local": "xe-0/0/5", "system": "cust-rtr-42", "port": "TenGigE0/0/0/1"},  # no ASN in the description
                {"local": "xe-0/0/7", "system": "edge01.cloudflare.example", "port": "Ethernet3/1"},
            ]
        ),
        "ixp-b": "",
    }

    def collect(targets, workers=50, timeout=60):
        return [
            CollectResult(t.device_id, True, config=configs[t.hostname], duration_ms=1, neighbors=lldp[t.hostname])
            for t in targets
        ]

    monkeypatch.setattr(engine, "nornir_collect", collect)
    plat = {p["slug"]: p["id"] for p in admin.get("/api/v1/platforms").json()}
    admin.post("/api/v1/credentials", json={"name": "c", "username": "u", "password": "p", "make_default": True})
    site = admin.post("/api/v1/sites", json={"name": "BOM", "slug": "bom"}).json()["id"]
    ids = {
        h: admin.post(
            "/api/v1/devices",
            json={"hostname": h, "management_ip": f"10.0.8.{n + 1}", "platform_id": plat["junos"], "site_id": site},
        ).json()["id"]
        for n, h in enumerate(configs)
    }
    admin.post("/api/v1/backups/run", json={"run_async": False})
    # IXP Manager: Cloudflare (also named on ixp-a's port) and Google on switch ixp-b
    for asn, name, switch in ((13335, "Cloudflare", "ixp-a"), (15169, "Google", "IXP-B")):
        db.add(
            IxpMember(
                tenant_id=tenant.id,
                asn=asn,
                name=name,
                connections=[{"ports": [{"switch": switch, "speed_mbps": 100000}], "vlans": []}],
            )
        )
    db.commit()

    t = admin.get("/api/v1/topology").json()
    nodes = {n["id"]: n for n in t["nodes"]}
    cust = {n["label"]: n for n in t["nodes"] if n["kind"] == "customer"}
    assert set(cust) == {"AS13335 Cloudflare", "AS15169 Google", "cust-rtr-42"}
    assert all(n["site_id"] == site for n in cust.values())
    edges = {(nodes[e["source"]]["label"], nodes[e["target"]]["label"]): e for e in t["edges"] if e.get("customer")}
    cf = edges[("ixp-a", "AS13335 Cloudflare")]
    # the port description gives the ASN, LLDP confirms it: one node, one link, no extra IXP Manager link
    assert cf["kind"] == "lldp" and cf["a_interface"] == "xe-0/0/7" and cf["b_interface"] == "Ethernet3/1"
    assert [k for k in edges if k[1] == "AS13335 Cloudflare"] == [("ixp-a", "AS13335 Cloudflare")]
    assert edges[("ixp-a", "cust-rtr-42")]["b_interface"] == "TenGigE0/0/0/1"
    assert edges[("ixp-b", "AS15169 Google")]["kind"] == "ixpmanager"
    # the fabric link and the spare port are not customers
    assert not any(k[0] == "ixp-a" and k[1] == "ixp-b" for k in edges)
    assert len(edges) == 3

    off = admin.get("/api/v1/topology", params={"sources": "lldp,subnet,description"}).json()
    assert not [n for n in off["nodes"] if n["kind"] == "customer"] and not [
        e for e in off["edges"] if e.get("customer")
    ]
    assert [e["kind"] for e in off["edges"]] == ["lldp"]
    per_site = admin.get("/api/v1/topology", params={"site_id": site}).json()
    assert len([n for n in per_site["nodes"] if n["kind"] == "customer"]) == 3
    assert {s["device_count"] for s in t["sites"]} == {2}  # customers are not devices
    assert ids
