"""Traffic graphs from IXP Manager's Grapher API, including member-to-member (P2P) graphs.

``/grapher/{graph}?type=log`` returns the series as rows ``[unix ts, avg in, avg out, max in,
max out]`` (bits/s for ``category=bits``), ``type=json`` the statistics. Aggregate graphs (``ixp``,
``infrastructure``, ``switch``, ``location``) come from MRTG, per-VLAN and member-to-member graphs
(``vlan``, ``vlaninterface``, ``p2p``) from sFlow. Member and P2P graphs need the API key of an IXP
Manager *superuser* (``GRAPHER_ACCESS_CUSTOMER`` / ``GRAPHER_ACCESS_P2P`` default to
``own_graphs_only``) - every failure is reported with the likely cause so an empty graph is never
silent.
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.security import decrypt_secret
from app.models import Integration

GRAPHS: dict[str, dict] = {
    # graph -> (id parameters, backend family, protocols)
    "ixp": {"ids": ("id",), "family": "mrtg"},
    "infrastructure": {"ids": ("id",), "family": "mrtg"},
    "location": {"ids": ("id",), "family": "mrtg"},
    "switch": {"ids": ("id",), "family": "mrtg"},
    "core-bundle": {"ids": ("id",), "family": "mrtg"},
    "physicalinterface": {"ids": ("id",), "family": "mrtg"},
    "virtualinterface": {"ids": ("id",), "family": "mrtg"},
    "customer": {"ids": ("id",), "family": "mrtg"},
    "vlan": {"ids": ("id",), "family": "sflow"},
    "vlaninterface": {"ids": ("id",), "family": "sflow"},
    "p2p": {"ids": ("svli", "dvli"), "family": "sflow"},
    "multip2p": {"ids": ("scid", "dcid"), "family": "sflow"},
}
PERIODS = ("day", "week", "month", "year")
CATEGORIES = ("bits", "pkts", "errs", "discs", "bcasts")
PROTOCOLS = ("all", "ipv4", "ipv6")
CACHE_SECONDS = 120


class GraphError(Exception):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason  # forbidden|not_found|unreachable|bad_response|invalid


@dataclass
class GraphResult:
    graph: str
    params: dict
    points: list[dict] = field(default_factory=list)  # {t, in, out, max_in, max_out}
    statistics: dict | None = None
    error: str | None = None
    reason: str | None = None  # why there is no data: forbidden|no_data|... (None when populated)

    def to_dict(self) -> dict:
        return {
            "graph": self.graph,
            "params": self.params,
            "points": self.points,
            "statistics": self.statistics,
            "error": self.error,
            "reason": self.reason,
        }


def normalise_params(graph: str, params: dict) -> dict:
    if graph not in GRAPHS:
        raise GraphError(f"unknown graph {graph!r}", "invalid")
    spec = GRAPHS[graph]
    out: dict[str, Any] = {}
    for key in spec["ids"]:
        v = params.get(key)
        if v in (None, ""):
            if graph == "ixp":
                v = 1
            else:
                raise GraphError(f"{graph} graphs need {key}", "invalid")
        try:
            out[key] = int(v)
        except (TypeError, ValueError) as e:
            raise GraphError(f"{key} must be a number", "invalid") from e
    period = params.get("period") or "day"
    category = params.get("category") or "bits"
    protocol = params.get("protocol") or ("all" if spec["family"] == "mrtg" else "ipv4")
    if period not in PERIODS or category not in CATEGORIES or protocol not in PROTOCOLS:
        raise GraphError("invalid period/category/protocol", "invalid")
    if spec["family"] == "mrtg":
        protocol = "all"  # MRTG graphs only exist for all protocols
    elif protocol == "all" and graph in ("vlan", "vlaninterface", "p2p"):
        protocol = "ipv4"  # sFlow graphs are per protocol
    out.update(period=period, category=category, protocol=protocol)
    return out


_cache: dict[tuple, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: tuple, fn):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = (now, value)
    return value


class Grapher:
    """Reads graphs from one IXP Manager integration (or synthetic ones for the demo tenant)."""

    def __init__(self, integration: Integration, client: httpx.Client | None = None, timeout: float = 30):
        self.integration = integration
        self.demo = bool((integration.options or {}).get("demo"))
        self.http = client or httpx.Client(
            base_url=integration.base_url.rstrip("/"),
            headers={"X-IXP-Manager-API-Key": decrypt_secret(integration.token_enc) or ""},
            timeout=timeout,
            follow_redirects=False,
        )

    # --- raw access --------------------------------------------------------------------------------

    def _get(self, graph: str, params: dict, kind: str):
        if self.demo:
            return _demo(graph, params, kind)
        try:
            r = self.http.get(f"/grapher/{graph}", params={**params, "type": kind})
        except httpx.HTTPError as e:
            raise GraphError(f"IXP Manager is not reachable: {e}", "unreachable") from e
        if r.status_code in (401, 403) or r.is_redirect:
            raise GraphError(
                "IXP Manager refused this graph. Member and P2P graphs need the API key of an IXP Manager "
                "superuser (GRAPHER_ACCESS_CUSTOMER / GRAPHER_ACCESS_P2P default to own_graphs_only).",
                "forbidden",
            )
        if r.status_code == 404:
            raise GraphError("IXP Manager does not know this graph or object id.", "not_found")
        if r.status_code >= 400:
            raise GraphError(f"IXP Manager answered HTTP {r.status_code}.", "bad_response")
        try:
            return r.json()
        except ValueError as e:
            raise GraphError(
                "IXP Manager did not return JSON (a login page?) - check the integration's API key.", "forbidden"
            ) from e

    def statistics(self, graph: str, params: dict) -> dict | None:
        p = normalise_params(graph, params)
        key = (self.integration.id, graph, "json", tuple(sorted(p.items())))
        toc = _cached(key, lambda: self._get(graph, p, "json"))
        stats = toc.get("statistics") if isinstance(toc, dict) else None
        return {k: v for k, v in stats.items() if isinstance(v, int | float)} if isinstance(stats, dict) else None

    def series(self, graph: str, params: dict) -> GraphResult:
        try:
            p = normalise_params(graph, params)
        except GraphError as e:
            return GraphResult(graph, params, error=str(e), reason=e.reason)
        res = GraphResult(graph, p)
        try:
            key = (self.integration.id, graph, "log", tuple(sorted(p.items())))
            rows = _cached(key, lambda: self._get(graph, p, "log"))
        except GraphError as e:
            res.error, res.reason = str(e), e.reason
            return res
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, list) and len(row) >= 3:
                ts, vin, vout = row[0], row[1], row[2]
                res.points.append(
                    {
                        "t": int(ts),
                        "in": vin,
                        "out": vout,
                        "max_in": row[3] if len(row) > 3 else vin,
                        "max_out": row[4] if len(row) > 4 else vout,
                    }
                )
        res.points.sort(key=lambda x: x["t"])
        try:
            res.statistics = self.statistics(graph, p)
        except GraphError:
            res.statistics = None
        if not res.points or not any(x["in"] or x["out"] for x in res.points):
            res.reason = "no_data"
            res.error = (
                "IXP Manager has no sFlow data for this graph: the sflow-to-rrd handler has not written the RRD "
                "file (P2P files exist only for member pairs that exchanged traffic; check sflowtool, the "
                "sflow-to-rrd-handler and GRAPHER_BACKEND_SFLOW_ENABLED)."
                if GRAPHS[graph]["family"] == "sflow"
                else "IXP Manager has no MRTG data for this graph: check that MRTG polls the switch ports "
                "(GRAPHER_BACKEND_MRTG_ENABLED, the generated MRTG config and its cron job)."
            )
            if res.points:  # zeros are data too: keep them, but say why the graph is flat
                res.reason = "all_zero"
        return res

    def p2p_matrix(self, src_vli: int, peers: list[tuple[int, dict]], params: dict, workers: int = 8) -> list[dict]:
        """Statistics of ``src_vli`` -> each peer vli; peers without data are reported, not dropped."""

        def one(peer: tuple[int, dict]) -> dict:
            dvli, info = peer
            row = {**info, "dvli": dvli}
            try:
                st = self.statistics("p2p", {**params, "svli": src_vli, "dvli": dvli}) or {}
            except GraphError as e:
                return {**row, "error": str(e), "reason": e.reason}
            row.update(
                {
                    k: st.get(k, 0)
                    for k in ("averagein", "averageout", "maxin", "maxout", "totalin", "totalout", "curin", "curout")
                }
            )
            return row

        with ThreadPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(one, peers))
        rows.sort(key=lambda r: -((r.get("totalin") or 0) + (r.get("totalout") or 0)))
        return rows


# --- demo -----------------------------------------------------------------------------------------

_DEMO_SCALE = {"ixp": 380e9, "infrastructure": 190e9, "switch": 60e9, "vlan": 160e9, "vlaninterface": 9e9, "p2p": 1.2e9}


def _demo(graph: str, params: dict, kind: str):
    """A diurnal curve, deterministic per graph and ids, so the demo tenant's graphs look plausible."""
    seed = sum(int(v) * (n + 7) for n, (k, v) in enumerate(sorted(params.items())) if k in ("id", "svli", "dvli"))
    scale = _DEMO_SCALE.get(graph, 5e9) * (0.35 + (seed % 13) / 13)
    if graph == "p2p" and seed % 5 == 0:
        scale = 0  # some pairs never exchange traffic
    step = {"day": 300, "week": 1800, "month": 7200, "year": 86400}[params["period"]]
    n = {"day": 288, "week": 336, "month": 360, "year": 365}[params["period"]]
    now = int(time.time()) // step * step
    rows = []
    for i in range(n):
        t = now - (n - i) * step
        hour = (t % 86400) / 3600
        shape = 0.55 + 0.45 * math.sin((hour - 9) / 24 * 2 * math.pi) + 0.05 * math.sin(i * 1.7 + seed)
        vin = int(scale * max(0.05, shape))
        vout = int(vin * (0.82 + (seed % 7) / 30))
        rows.append([t, vin, vout, int(vin * 1.15), int(vout * 1.15)])
    if kind == "log":
        return rows
    vals_in = [r[1] for r in rows]
    vals_out = [r[2] for r in rows]
    return {
        "class": graph,
        "statistics": {
            "totalin": sum(vals_in) * step,
            "totalout": sum(vals_out) * step,
            "curin": vals_in[-1],
            "curout": vals_out[-1],
            "averagein": sum(vals_in) / n,
            "averageout": sum(vals_out) / n,
            "maxin": max(r[3] for r in rows),
            "maxout": max(r[4] for r in rows),
        },
    }
