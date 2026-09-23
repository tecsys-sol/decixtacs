"""Module 15 - IXP Manager connector + route-server (BIRD / birdseye) awareness.

* Members, ports, VLANs, IPs and route-server participation come from the standard IX-F Member
  Export (``/api/v4/member-export/ixf/1.0``) that every IXP Manager exposes.
* Traffic statistics come from IXP Manager's Grapher API (``/grapher/{graph}?type=json``).
* Route-server client state comes from the IXP Manager looking glass / birdseye API
  (``/api/protocols/bgp``) of each BIRD route server, including accepted/filtered prefix counts.
  Filter reasons are decoded from IXP Manager's large communities (``RS_ASN:1101:X``), and RPKI
  state from ``RS_ASN:1000:X`` - the code table below follows IXP Manager's default route-server
  template; override it via ``options.filter_codes`` if you run a modified template.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import Integration, IxpMember, RouteServerClient
from app.services import metrics

log = logging.getLogger(__name__)

FILTER_CODES = {
    1: "prefix length too long",
    2: "prefix length too short",
    3: "bogon prefix",
    4: "bogon ASN in path",
    5: "AS path too long",
    6: "AS path too short",
    7: "first AS != peer AS",
    8: "next hop != peer IP",
    9: "IRR: prefix not in origin AS set",
    10: "IRR: origin AS not in AS-SET",
    11: "RPKI unknown",
    12: "RPKI invalid",
    13: "transit-free ASN in path",
    14: "too many communities",
}
IRR_CODES = {9, 10}
RPKI_CODES = {1: "valid", 2: "unknown", 3: "not_checked"}


class IxpManagerClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"X-IXP-Manager-API-Key": api_key}, timeout=timeout
        )

    def ixf_export(self) -> dict:
        r = self.http.get("/api/v4/member-export/ixf/1.0")
        r.raise_for_status()
        return r.json()

    def graph(self, graph: str, params: dict) -> Any:
        r = self.http.get(f"/grapher/{graph}", params={"type": "json", **params})
        r.raise_for_status()
        return r.json()


class BirdseyeClient:
    def __init__(self, base_url: str, timeout: float = 30):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def bgp_protocols(self) -> dict:
        r = self.http.get("/api/protocols/bgp")
        r.raise_for_status()
        return r.json().get("protocols", {})

    def filtered_routes(self, protocol: str) -> list[dict]:
        r = self.http.get(f"/api/routes/filtered/{protocol}")
        r.raise_for_status()
        return r.json().get("routes", [])


def sync_members(db: Session, integration: Integration, client: IxpManagerClient | None = None) -> dict:
    client = client or IxpManagerClient(integration.base_url, decrypt_secret(integration.token_enc) or "")
    data = client.ixf_export()
    switches = {sw["id"]: sw.get("name") for ixp in data.get("ixp_list", []) for sw in ixp.get("switch", [])}
    vlans = {v["id"]: v.get("name") for ixp in data.get("ixp_list", []) for v in ixp.get("vlan", [])}
    existing = {m.asn: m for m in db.scalars(select(IxpMember).where(IxpMember.tenant_id == integration.tenant_id))}
    n = 0
    for mem in data.get("member_list", []):
        asn = mem.get("asnum")
        if asn is None:
            continue
        m = existing.get(asn)
        if m is None:
            m = IxpMember(tenant_id=integration.tenant_id, asn=asn, name=mem.get("name") or f"AS{asn}")
            db.add(m)
            existing[asn] = m
        m.name = mem.get("name") or m.name
        m.url = mem.get("url")
        m.peering_policy = mem.get("peering_policy")
        m.member_type = mem.get("member_type")
        m.contacts = mem.get("contact_email", [])
        conns = []
        for c in mem.get("connection_list", []):
            conns.append(
                {
                    "state": c.get("state"),
                    "ports": [
                        {
                            "switch": switches.get(i.get("switch_id"), i.get("switch_id")),
                            "speed_mbps": i.get("if_speed"),
                        }
                        for i in c.get("if_list", [])
                    ],
                    "vlans": [
                        {
                            "vlan_id": v.get("vlan_id"),
                            "vlan": vlans.get(v.get("vlan_id")),
                            "ipv4": (v.get("ipv4") or {}).get("address"),
                            "ipv6": (v.get("ipv6") or {}).get("address"),
                            "rs_client_v4": bool((v.get("ipv4") or {}).get("routeserver")),
                            "rs_client_v6": bool((v.get("ipv6") or {}).get("routeserver")),
                            "as_macro": (v.get("ipv4") or {}).get("as_macro") or (v.get("ipv6") or {}).get("as_macro"),
                            "max_prefix_v4": (v.get("ipv4") or {}).get("max_prefix"),
                            "max_prefix_v6": (v.get("ipv6") or {}).get("max_prefix"),
                        }
                        for v in c.get("vlan_list", [])
                    ],
                }
            )
        m.connections = conns
        n += 1
    integration.last_sync_at = utcnow()
    integration.last_sync_status = "success"
    integration.last_sync_detail = {"members": n}
    metrics.SYNC_RUNS.labels(kind="ixpmanager", status="success").inc()
    db.flush()
    return {"members": n}


def _decode_communities(route: dict, rs_asn: int | None) -> tuple[set[int], str | None]:
    reasons: set[int] = set()
    rpki = None
    for lc in (route.get("bgp") or {}).get("large_communities", []):
        if len(lc) != 3 or (rs_asn and lc[0] != rs_asn):
            continue
        if lc[1] == 1101:
            reasons.add(lc[2])
        elif lc[1] == 1000:
            rpki = RPKI_CODES.get(lc[2], rpki)
    if 12 in reasons:
        rpki = "invalid"
    return reasons, rpki


def sync_route_server(db: Session, integration: Integration, client: BirdseyeClient | None = None) -> dict:
    """``integration.kind == 'birdseye'``; ``options``: {"name": "rs1-v4", "rs_asn": 65000, "filter_reasons": true}."""
    opts = integration.options or {}
    rs_name = opts.get("name") or integration.name
    client = client or BirdseyeClient(integration.base_url)
    protos = client.bgp_protocols()
    existing = {
        c.protocol_name: c
        for c in db.scalars(
            select(RouteServerClient).where(
                RouteServerClient.tenant_id == integration.tenant_id, RouteServerClient.route_server == rs_name
            )
        )
    }
    for pname, p in protos.items():
        asn = p.get("neighbor_as")
        if not asn:
            continue
        c = existing.get(pname)
        if c is None:
            c = RouteServerClient(
                tenant_id=integration.tenant_id,
                route_server=rs_name,
                protocol_name=pname,
                asn=asn,
                neighbor_address=p.get("neighbor_address", ""),
                address_family="ipv6" if ":" in str(p.get("neighbor_address", "")) else "ipv4",
                state="unknown",
            )
            db.add(c)
        routes = p.get("routes") or {}
        c.asn = asn
        c.state = str(p.get("state") or p.get("bgp_state") or "unknown")
        c.prefixes_accepted = int(routes.get("imported") or 0)
        c.prefixes_filtered = int(routes.get("filtered") or 0)
        c.prefixes_exported = int(routes.get("exported") or 0)
        c.since = p.get("state_changed")
        if opts.get("filter_reasons") and c.prefixes_filtered:
            irr = rpki_inv = 0
            rpki: dict[str, int] = {}
            try:
                for route in client.filtered_routes(pname):
                    reasons, state = _decode_communities(route, opts.get("rs_asn"))
                    irr += bool(reasons & IRR_CODES)
                    rpki_inv += state == "invalid"
                    if state:
                        rpki[state] = rpki.get(state, 0) + 1
            except httpx.HTTPError:
                log.warning("could not fetch filtered routes for %s", pname, exc_info=True)
            c.irr_filtered, c.rpki_invalid, c.rpki_status = irr, rpki_inv, rpki
            c.irr_status = "filtered" if irr else "ok"
        elif not c.prefixes_filtered:
            c.irr_filtered = c.rpki_invalid = 0
            c.irr_status = "ok"
    integration.last_sync_at = utcnow()
    integration.last_sync_status = "success"
    integration.last_sync_detail = {"protocols": len(protos)}
    metrics.SYNC_RUNS.labels(kind="birdseye", status="success").inc()
    db.flush()
    return {"protocols": len(protos)}
