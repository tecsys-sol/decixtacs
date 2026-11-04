import time

from app.services.integrations import grapher, ixpmanager
from tests.test_ixp_graphs import FakeIxpm, _integration


def _flat(sflow_v4: int, sflow_v6: int, mrtg: int, outage_at: int | None = None):
    """Constant traffic per graph; sFlow drops to nothing at one point when outage_at is set."""

    def demo(graph, params, kind):
        now = int(time.time()) // 300 * 300
        value = {"infrastructure": mrtg, "vlan": sflow_v4 if params.get("protocol") == "ipv4" else sflow_v6}.get(
            graph, 0
        )
        rows = []
        for k in range(288):
            t = now - (288 - k) * 300
            v = 0 if graph == "vlan" and outage_at is not None and k == outage_at else value
            rows.append([t, v, v, v, v])
        return rows if kind == "log" else {"statistics": {}}

    return demo


def test_no_integration(admin):
    assert admin.get("/api/v1/ixp/sflow-coverage").json()["reason"] == "no_integration"


def test_coverage_ratio_and_verdicts(admin, db, tenant, monkeypatch):
    i = _integration(db, tenant, demo=True)
    ixpmanager.sync_members(db, i, client=FakeIxpm())
    db.commit()

    # sFlow sees 700 of every 1000 bits the member ports carry, and is out for one 5-minute point
    monkeypatch.setattr(grapher, "_demo", _flat(600, 100, 1000, outage_at=10))
    grapher._cache.clear()
    r = admin.get("/api/v1/ixp/sflow-coverage").json()
    infra = r["infrastructures"][0]
    assert infra["name"] == "DE-CIX Mumbai" and infra["bucket_seconds"] == 300
    assert infra["verdict"] == "loss" and "70%" in infra["message"]
    assert infra["outage_points"] == 1
    assert infra["ratio"] == 0.7 and infra["ratio_p10"] == 0.7
    assert len(infra["series"]) == 288

    # more than the ports carried: double sampling
    monkeypatch.setattr(grapher, "_demo", _flat(1000, 150, 1000))
    grapher._cache.clear()
    infra = admin.get("/api/v1/ixp/sflow-coverage").json()["infrastructures"][0]
    assert infra["verdict"] == "double" and infra["ratio"] == 1.15

    monkeypatch.setattr(grapher, "_demo", _flat(900, 60, 1000))
    grapher._cache.clear()
    infra = admin.get("/api/v1/ixp/sflow-coverage", params={"period": "day"}).json()["infrastructures"][0]
    assert infra["verdict"] == "ok"
    assert admin.get("/api/v1/ixp/sflow-coverage", params={"period": "year"}).status_code == 422
