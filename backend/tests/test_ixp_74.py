"""IXP Manager 7.4.0 behaviour (Grapher routes, API key errors, custom periods) and the member
graph / P2P features built on top of it."""

import csv
import io
import uuid

import httpx

from app.models import RouteServerClient
from app.services.integrations import grapher, ixpmanager
from tests.test_ixp_graphs import FakeIxpm, _integration


def _g(handler) -> grapher.Grapher:
    from app.models import Integration

    i = Integration(kind="ixpmanager", name="x", base_url="https://ixp.example", options={})
    i.id = uuid.uuid4()
    return grapher.Grapher(
        i, client=httpx.Client(base_url="https://ixp.example", transport=httpx.MockTransport(handler))
    )


def test_v74_route_names_and_api_key_errors():
    seen = []

    def ok(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json=[[1, 5, 6, 7, 8]] if req.url.params["type"] == "log" else {"statistics": {}})

    assert _g(ok).series("corebundle", {"id": 3}).reason is None and seen[0] == "/grapher/corebundle"
    assert _g(ok).series("core-bundle", {"id": 3}).reason == "invalid"  # 7.4.0 has no such route
    for body in ("API key expired", "Invalid credentials", "Malformed API key structure", "User is disabled"):
        r = _g(lambda req, b=body: httpx.Response(401, text=b)).series("ixp", {})
        assert r.reason == "auth" and body in r.error and "superuser" in r.error
    forbidden = _g(lambda req: httpx.Response(403, text="This action is unauthorized.")).series(
        "p2p", {"svli": 1, "dvli": 2}
    )
    assert forbidden.reason == "forbidden" and "own_graphs_only" in forbidden.error


def test_custom_period_for_p2p():
    calls = []

    def ok(req: httpx.Request):
        calls.append(dict(req.url.params))
        if req.url.params["type"] == "log":
            return httpx.Response(200, json=[[1760000000 + 300 * k, k, 2 * k, k, 2 * k] for k in range(1, 101)])
        return httpx.Response(200, json={"statistics": {"averagein": 50.5}})

    r = _g(ok).series(
        "p2p",
        {
            "svli": 5,
            "dvli": 9,
            "period": "custom",
            "period_start": "2026-10-01T10:00",
            "period_end": "2026-10-02 09:30+05:30",
        },
    )
    assert r.reason is None
    assert calls[0]["period"] == "custom"
    assert (calls[0]["period_start"], calls[0]["period_end"]) == ("2026-10-01T10:00:00Z", "2026-10-02T04:00:00Z")
    d = r.to_dict()["derived"]
    # 95th percentile of 1..100 = 95 (in) / 190 (out); 5-minute samples
    assert (d["p95_in"], d["p95_out"], d["p95"], d["step_seconds"], d["samples"]) == (95, 190, 190, 300, 100)
    bad = [
        (
            "ixp",
            {"period": "custom", "period_start": "2026-10-01", "period_end": "2026-10-02"},
        ),  # MRTG: no custom range
        ("p2p", {"svli": 1, "dvli": 2, "period": "custom", "period_start": "2026-10-01"}),
        ("p2p", {"svli": 1, "dvli": 2, "period": "custom", "period_start": "2026-10-02", "period_end": "2026-10-01"}),
        ("p2p", {"svli": 1, "dvli": 2, "period": "custom", "period_start": "2024-01-01", "period_end": "2026-01-01"}),
        ("p2p", {"svli": 1, "dvli": 2, "period": "custom", "period_start": "yesterday", "period_end": "2026-01-01"}),
    ]
    for graph, params in bad:
        assert _g(ok).series(graph, params).reason == "invalid", params


def _members(admin, db, tenant):
    i = _integration(db, tenant, demo=True)
    ixpmanager.sync_members(db, i, client=FakeIxpm())
    db.add(
        RouteServerClient(
            tenant_id=tenant.id,
            route_server="rs1",
            protocol_name="pb_1",
            asn=15169,
            neighbor_address="185.1.0.2",
            address_family="ipv4",
            state="up",
        )
    )
    db.commit()


def test_member_p2p_share_protocols_and_opportunities(admin, db, tenant, monkeypatch):
    _members(admin, db, tenant)
    # make one pair silent: P2P RRD files only exist for pairs that exchanged sampled traffic
    real = grapher._demo

    def demo(graph, params, kind):
        if graph == "p2p" and params.get("dvli") == 503:
            rows = [[1, 0, 0, 0, 0]]
            return rows if kind == "log" else {"statistics": {"totalin": 0, "totalout": 0}}
        return real(graph, params, kind)

    monkeypatch.setattr(grapher, "_demo", demo)
    grapher._cache.clear()
    r = admin.get("/api/v1/ixp/members/13335/p2p", params={"protocol": "both"}).json()
    assert r["capacity_mbps"] == 100000 and r["peers_with_traffic"] == 1
    busy = r["peers"][0]
    assert busy["asn"] == 15169 and busy["share"] == 100.0 and set(busy["by_protocol"]) == {"ipv4", "ipv6"}
    assert busy["totalin"] == busy["by_protocol"]["ipv4"]["totalin"] + busy["by_protocol"]["ipv6"]["totalin"]
    assert busy["rs_sessions"] == {"up": 1, "down": 0}
    assert [o["asn"] for o in r["opportunities"]] == [6939]
    assert r["opportunities"][0]["hint"]
    assert admin.get("/api/v1/ixp/members/13335/p2p", params={"protocol": "all"}).status_code == 422

    custom = admin.get(
        "/api/v1/ixp/graph",
        params={
            "graph": "p2p",
            "svli": 501,
            "dvli": 502,
            "period": "custom",
            "period_start": "2026-10-01",
            "period_end": "2026-10-03",
        },
    ).json()
    assert custom["reason"] is None and custom["derived"]["p95"] > 0 and custom["params"]["period"] == "custom"


def test_graph_csv_and_p2p_matrix(admin, db, tenant):
    _members(admin, db, tenant)
    grapher._cache.clear()
    r = admin.get("/api/v1/ixp/graph.csv", params={"graph": "vlaninterface", "id": 501, "protocol": "ipv6"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="vlaninterface-501-ipv6-day.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["timestamp_utc", "avg_in_bps", "avg_out_bps", "max_in_bps", "max_out_bps"] and len(rows) == 289
    assert admin.get("/api/v1/ixp/graph.csv", params={"graph": "nope"}).status_code == 422

    m = admin.get("/api/v1/ixp/p2p-matrix", params={"top": 3}).json()
    assert m["reason"] is None and len(m["members"]) == 3 and m["vlan_id"] == 2
    assert all(m["cells"][k][k] is None for k in range(3))
    assert all(isinstance(m["cells"][a][b], int | float) for a in range(3) for b in range(3) if a != b)
