import uuid

import httpx
import pytest

from app.models import Integration
from app.services.integrations import grapher, ixpmanager

PEERS = [(13335, "Cloudflare"), (15169, "Google"), (6939, "Hurricane Electric")]


class FakeIxpm:
    def __init__(self, macs_status: int | None = None):
        self.macs_status = macs_status

    def ixf_export(self) -> dict:
        return {
            "ixp_list": [
                {
                    "ixp_id": 1,
                    "shortname": "DE-CIX Mumbai",
                    "switch": [{"id": 7, "name": "bom-sw1"}],
                    "vlan": [{"id": 2, "name": "Peering LAN"}],
                }
            ],
            "member_list": [
                {
                    "asnum": asn,
                    "name": name,
                    "connection_list": [
                        {
                            "ixp_id": 1,
                            "state": "active",
                            "if_list": [{"switch_id": 7, "if_speed": 100000}],
                            "vlan_list": [
                                {
                                    "vlan_id": 2,
                                    "ipv4": {"address": f"185.1.0.{k}", "mac_addresses": [f"02:00:00:00:00:{k:02x}"]},
                                }
                            ],
                        }
                    ],
                }
                for k, (asn, name) in enumerate(PEERS, 1)
            ],
        }

    def configured_macs(self) -> dict:
        if self.macs_status:
            req = httpx.Request("GET", "http://x/api/v4/sflow-db-mapper/configured-macs")
            raise httpx.HTTPStatusError("denied", request=req, response=httpx.Response(self.macs_status, request=req))
        # IXP Manager stores MACs without separators
        return {"1": {"100": {f"0200000000{k:02x}": 500 + k for k in range(1, len(PEERS) + 1)}}}


def _integration(db, tenant, name="ixpm", **options) -> Integration:
    i = Integration(tenant_id=tenant.id, kind="ixpmanager", name=name, base_url="https://ixp.example", options=options)
    db.add(i)
    db.flush()
    return i


def test_sync_maps_members_to_vlan_interfaces(db, tenant):
    i = _integration(db, tenant)
    assert ixpmanager.sync_members(db, i, client=FakeIxpm()) == {"members": 3, "vlan_interfaces": 3}
    db.commit()
    from app.models import IxpMember

    cf = db.query(IxpMember).filter_by(asn=13335).one()
    v = cf.connections[0]["vlans"][0]
    assert (v["vlan_id"], v["vli_id"], v["tag"]) == (2, 501, 100) and cf.connections[0]["ixp_id"] == 1
    assert i.last_sync_detail["vlan_interface_lookup"] == "ok"
    assert i.last_sync_detail["fabric"] == [
        {
            "id": 1,
            "name": "DE-CIX Mumbai",
            "switches": [{"id": 7, "name": "bom-sw1"}],
            "vlans": [{"id": 2, "name": "Peering LAN"}],
        }
    ]

    j = _integration(db, tenant, name="ixpm2")
    ixpmanager.sync_members(db, j, client=FakeIxpm(macs_status=403))
    assert (
        j.last_sync_detail["vlan_interface_lookup"].startswith("forbidden")
        and j.last_sync_detail["vlan_interfaces"] == 0
    )


def _grapher(handler) -> grapher.Grapher:
    i = Integration(kind="ixpmanager", name="x", base_url="https://ixp.example", options={})
    i.id = uuid.uuid4()
    return grapher.Grapher(
        i, client=httpx.Client(base_url="https://ixp.example", transport=httpx.MockTransport(handler))
    )


def test_grapher_series_and_failure_reasons():
    calls = []

    def ok(req: httpx.Request):
        calls.append(dict(req.url.params))
        if req.url.params["type"] == "log":
            return httpx.Response(200, json=[[1700000300, 10, 20, 30, 40], [1700000000, 1, 2, 3, 4]])
        return httpx.Response(200, json={"statistics": {"averagein": 5.5, "maxin": 30, "maxinat": None}})

    r = _grapher(ok).series("p2p", {"svli": 5, "dvli": 6, "period": "week"})
    assert r.reason is None and [p["t"] for p in r.points] == [1700000000, 1700000300]
    assert r.points[1] == {"t": 1700000300, "in": 10, "out": 20, "max_in": 30, "max_out": 40}
    assert r.statistics == {"averagein": 5.5, "maxin": 30}
    assert calls[0] == {
        "svli": "5",
        "dvli": "6",
        "period": "week",
        "category": "bits",
        "protocol": "ipv4",
        "type": "log",
    }

    assert _grapher(lambda req: httpx.Response(403)).series("vlaninterface", {"id": 1}).reason == "forbidden"
    html = _grapher(lambda req: httpx.Response(200, text="<html>login</html>")).series("ixp", {})
    assert html.reason == "forbidden" and "API key" in html.error
    empty = _grapher(lambda req: httpx.Response(200, json=[])).series("p2p", {"svli": 1, "dvli": 2})
    assert empty.reason == "no_data" and "sflow-to-rrd" in empty.error
    flat = _grapher(lambda req: httpx.Response(200, json=[[1, 0, 0, 0, 0]] if req.url.params["type"] == "log" else {}))
    assert flat.series("ixp", {}).reason == "all_zero"
    assert _grapher(ok).series("p2p", {"svli": 1}).reason == "invalid"
    with pytest.raises(grapher.GraphError):
        grapher.normalise_params("rm-rf", {})
    # MRTG graphs only exist for all protocols; sFlow graphs need one
    assert grapher.normalise_params("switch", {"id": 1, "protocol": "ipv6"})["protocol"] == "all"
    assert grapher.normalise_params("vlan", {"id": 1, "protocol": "all"})["protocol"] == "ipv4"


def test_ixp_graph_api(admin, db, tenant):
    r = admin.get("/api/v1/ixp/graph", params={"graph": "ixp"}).json()
    assert r["reason"] == "no_integration" and r["points"] == []
    assert admin.get("/api/v1/ixp/fabric").json()["integration"] is None

    i = _integration(db, tenant, demo=True)
    ixpmanager.sync_members(db, i, client=FakeIxpm())
    db.commit()

    g = admin.get("/api/v1/ixp/graph", params={"graph": "ixp", "period": "day"}).json()
    assert g["reason"] is None and len(g["points"]) == 288 and g["statistics"]["maxin"] > 0
    fab = admin.get("/api/v1/ixp/fabric").json()
    assert fab["integration"]["vlan_interfaces"] == 3 and fab["fabric"][0]["switches"][0]["name"] == "bom-sw1"

    p2p = admin.get("/api/v1/ixp/members/13335/p2p").json()
    assert p2p["svli"] == 501 and p2p["vlan_id"] == 2 and p2p["peers_total"] == 2
    assert {x["asn"] for x in p2p["peers"]} == {15169, 6939}
    totals = [(x.get("totalin") or 0) + (x.get("totalout") or 0) for x in p2p["peers"]]
    assert totals == sorted(totals, reverse=True)
    assert admin.get("/api/v1/ixp/members/64999/p2p").status_code == 404

    health = admin.get("/api/v1/ixp/graphs/health").json()
    assert [c["graph"] for c in health["checks"]] == ["ixp", "switch", "vlan", "vlaninterface", "p2p"]
    assert all(c["points"] for c in health["checks"] if c["ok"])


def test_p2p_without_vlan_interface_ids_explains_why(admin, db, tenant):
    i = _integration(db, tenant, demo=True)
    ixpmanager.sync_members(db, i, client=FakeIxpm(macs_status=401))
    db.commit()
    r = admin.get("/api/v1/ixp/members/13335/p2p").json()
    assert r["reason"] == "no_vlan_interface" and "superuser" in r["error"]
    checks = {c["graph"]: c for c in admin.get("/api/v1/ixp/graphs/health").json()["checks"]}
    assert checks["ixp"]["ok"] and not checks["p2p"]["ok"] and "forbidden" in checks["p2p"]["error"]
