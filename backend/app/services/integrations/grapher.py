"""Traffic graphs from IXP Manager's Grapher API, including member-to-member (P2P) graphs.

``/grapher/{graph}?type=log`` returns the series as rows ``[unix ts, avg in, avg out, max in,
max out]`` (bits/s for ``category=bits``), ``type=json`` the statistics. Aggregate graphs (``ixp``,
``infrastructure``, ``switch``, ``location``) come from MRTG, per-VLAN and member-to-member graphs
(``vlan``, ``vlaninterface``, ``p2p``) from sFlow. Member and P2P graphs need the API key of an IXP
Manager *superuser* (``GRAPHER_ACCESS_CUSTOMER`` / ``GRAPHER_ACCESS_P2P`` default to
``own_graphs_only``) - every failure is reported with the likely cause so an empty graph is never
silent.

Checked against IXP Manager 7.4.0: Grapher routes (``corebundle``, not ``core-bundle``), API keys
(legacy and ``ixpm_`` keys, which can expire), and ``period=custom`` with ``period_start`` /
``period_end`` for the sFlow drill-down graphs (``p2p``, ``multip2p``).
"""

from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    "corebundle": {"ids": ("id",), "family": "mrtg"},
    "physicalinterface": {"ids": ("id",), "family": "mrtg"},
    "virtualinterface": {"ids": ("id",), "family": "mrtg"},
    "customer": {"ids": ("id",), "family": "mrtg"},
    "vlan": {"ids": ("id",), "family": "sflow"},
    "vlaninterface": {"ids": ("id",), "family": "sflow"},
    "p2p": {"ids": ("svli", "dvli"), "family": "sflow"},
    "multip2p": {"ids": ("scid", "dcid"), "family": "sflow"},
}
PERIODS = ("day", "week", "month", "year")
CUSTOM_PERIOD_GRAPHS = ("p2p", "multip2p")  # IXP Manager's PERIODS_EXTENDED (7.x)
MAX_CUSTOM_DAYS = 400
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

    def derived(self) -> dict:
        """What IXP Manager does not report: 95th percentile (of the samples' averages, at the period's
        resolution: 5 min for a day, 30 min for a week, 2 h for a month), sample step and coverage."""
        if not self.points:
            return {}
        ins = sorted(p["in"] or 0 for p in self.points)
        outs = sorted(p["out"] or 0 for p in self.points)

        def p95(vals: list) -> float:
            return vals[max(0, math.ceil(len(vals) * 0.95) - 1)]

        steps = [b["t"] - a["t"] for a, b in zip(self.points, self.points[1:], strict=False) if b["t"] > a["t"]]
        step = sorted(steps)[len(steps) // 2] if steps else None
        return {
            "p95_in": p95(ins),
            "p95_out": p95(outs),
            "p95": max(p95(ins), p95(outs)),
            "peak_in": max(p["max_in"] or 0 for p in self.points),
            "peak_out": max(p["max_out"] or 0 for p in self.points),
            "step_seconds": step,
            "samples": len(self.points),
            "first": self.points[0]["t"],
            "last": self.points[-1]["t"],
        }

    def to_dict(self) -> dict:
        return {
            "graph": self.graph,
            "params": self.params,
            "points": self.points,
            "statistics": self.statistics,
            "derived": self.derived(),
            "error": self.error,
            "reason": self.reason,
        }


def _when(v) -> datetime:
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError as e:
            raise GraphError(f"invalid date {v!r} (use ISO 8601, e.g. 2026-10-01T00:00)", "invalid") from e
    return d if d.tzinfo else d.replace(tzinfo=UTC)


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
    if period == "custom":
        if graph not in CUSTOM_PERIOD_GRAPHS:
            raise GraphError("a custom date range is only available for P2P graphs", "invalid")
        if not params.get("period_start") or not params.get("period_end"):
            raise GraphError("a custom date range needs period_start and period_end", "invalid")
        start, end = _when(params["period_start"]), _when(params["period_end"])
        if end <= start:
            raise GraphError("period_end must be after period_start", "invalid")
        if end - start > timedelta(days=MAX_CUSTOM_DAYS):
            raise GraphError(f"a custom date range can span at most {MAX_CUSTOM_DAYS} days", "invalid")
        # whole minutes, UTC: stable cache keys and what Carbon::parse() reads unambiguously
        out["period_start"] = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:00Z")
        out["period_end"] = end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:00Z")
    elif period not in PERIODS:
        raise GraphError("invalid period", "invalid")
    if category not in CATEGORIES or protocol not in PROTOCOLS:
        raise GraphError("invalid category/protocol", "invalid")
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
        if r.status_code == 401:
            # IXP Manager 7.x says why: "API key expired", "Valid API key required", "User is disabled", ...
            why = _short_text(r.text) or "unauthorised"
            raise GraphError(
                f"IXP Manager rejected the integration's API key: {why}. Create a new API key for an IXP Manager "
                "superuser and update the integration.",
                "auth",
            )
        if r.status_code == 403 or r.is_redirect:
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
        """IXP Manager's own statistics (averages, maxima, totals) for the graph."""
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


def _short_text(body: str) -> str:
    """A plain-text error from IXP Manager, without HTML or noise."""
    text = re.sub(r"<[^>]+>", " ", body or "")
    return re.sub(r"\s+", " ", text).strip()[:200]


# --- demo -----------------------------------------------------------------------------------------

_DEMO_SCALE = {"ixp": 380e9, "infrastructure": 190e9, "switch": 60e9, "vlan": 160e9, "vlaninterface": 9e9, "p2p": 1.2e9}


def _demo(graph: str, params: dict, kind: str):
    """A diurnal curve, deterministic per graph and ids, so the demo tenant's graphs look plausible."""
    seed = sum(int(v) * (n + 7) for n, (k, v) in enumerate(sorted(params.items())) if k in ("id", "svli", "dvli"))
    scale = _DEMO_SCALE.get(graph, 5e9) * (0.35 + (seed % 13) / 13)
    if graph == "p2p" and seed % 5 == 0:
        scale = 0  # some pairs never exchange traffic
    if params["period"] == "custom":
        t0 = int(_when(params["period_start"]).timestamp())
        t1 = int(_when(params["period_end"]).timestamp())
        span = max(t1 - t0, 300)
        step = 300 if span <= 2 * 86400 else 1800 if span <= 14 * 86400 else 7200 if span <= 62 * 86400 else 86400
        n = max(1, span // step)
        now = t1 // step * step + step
    else:
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
