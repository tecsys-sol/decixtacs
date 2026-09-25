"""IPAM read views over the NetBox mirror: prefixes, VLANs, IP addresses and VRFs.

NetBox stays the source of truth; the sync stores its objects in ``external_objects`` and these
endpoints flatten them into tables with filters and cross-references to inventory devices.
"""

from __future__ import annotations

import ipaddress
from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import Ctx, require
from app.models import Device, ExternalObject

router = APIRouter(prefix="/ipam", tags=["ipam"])

KINDS = {"prefixes": "prefix", "vlans": "vlan", "ip-addresses": "ip", "vrfs": "vrf"}


def _name(o: Any) -> str | None:
    if not isinstance(o, dict):
        return None
    return o.get("name") or o.get("display") or (str(o["vid"]) if "vid" in o else None)


def _choice(o: Any) -> str | None:
    return (o.get("value") or o.get("label")) if isinstance(o, dict) else (o or None)


def _site(nb: dict) -> str | None:
    if nb.get("site"):
        return _name(nb["site"])
    if nb.get("scope") and str(nb.get("scope_type", "")).endswith("site"):  # NetBox 4.2+ prefix scope
        return _name(nb["scope"])
    return _name(nb.get("scope"))


def _web(nb: dict) -> str | None:
    if nb.get("display_url"):
        return nb["display_url"]
    url = nb.get("url")
    return url.replace("/api/", "/", 1) if isinstance(url, str) else None


def _net(value: str | None):
    try:
        return ipaddress.ip_interface(value or "")
    except ValueError:
        return None


def _prefix(nb: dict, _: dict) -> dict:
    vlan = nb.get("vlan") or {}
    return {
        "prefix": nb.get("prefix"),
        "family": 6 if ":" in str(nb.get("prefix")) else 4,
        "status": _choice(nb.get("status")),
        "site": _site(nb),
        "vrf": _name(nb.get("vrf")),
        "vlan": f"{vlan.get('vid')} {vlan.get('name') or ''}".strip() if vlan else None,
        "tenant": _name(nb.get("tenant")),
        "role": _name(nb.get("role")),
        "description": nb.get("description") or None,
        "is_pool": bool(nb.get("is_pool")),
        "depth": int(nb.get("_depth") or 0),
        "children": int(nb.get("children") or 0),
    }


def _vlan(nb: dict, ctx: dict) -> dict:
    return {
        "vid": nb.get("vid"),
        "name": nb.get("name"),
        "status": _choice(nb.get("status")),
        "site": _site(nb),
        "group": _name(nb.get("group")),
        "tenant": _name(nb.get("tenant")),
        "role": _name(nb.get("role")),
        "description": nb.get("description") or None,
        "prefixes": ctx["prefixes_per_vlan"].get(nb.get("id"), []),
    }


def _ip(nb: dict, ctx: dict) -> dict:
    ao = nb.get("assigned_object") or {}
    dev = ao.get("device") or ao.get("virtual_machine") or {}
    dev_name = _name(dev)
    portal = ctx["devices"].get((dev_name or "").lower())
    return {
        "address": nb.get("address"),
        "family": 6 if ":" in str(nb.get("address")) else 4,
        "status": _choice(nb.get("status")),
        "role": _choice(nb.get("role")),
        "dns_name": nb.get("dns_name") or None,
        "vrf": _name(nb.get("vrf")),
        "device": dev_name,
        "device_id": str(portal) if portal else None,
        "interface": ao.get("name") if ao else None,
        "tenant": _name(nb.get("tenant")),
        "description": nb.get("description") or None,
    }


def _vrf(nb: dict, ctx: dict) -> dict:
    return {
        "name": nb.get("name"),
        "rd": nb.get("rd") or None,
        "tenant": _name(nb.get("tenant")),
        "description": nb.get("description") or None,
        "prefixes": ctx["prefixes_per_vrf"].get(nb.get("name"), 0),
    }


FLATTEN = {"prefix": _prefix, "vlan": _vlan, "ip": _ip, "vrf": _vrf}


def _sort_key(kind: str, row: dict):
    if kind == "prefix":
        n = _net(row["prefix"])
        return (row["vrf"] or "", n.version if n else 9, n.network if n else ipaddress.ip_network("0.0.0.0/0"))
    if kind == "ip":
        n = _net(row["address"])
        return (row["vrf"] or "", n.version if n else 9, int(n.ip) if n else 0)
    if kind == "vlan":
        return (row["site"] or "", row["vid"] or 0)
    return (row.get("name") or "",)


def _objects(ctx: Ctx, otype: str) -> list[ExternalObject]:
    return list(
        ctx.db.scalars(
            select(ExternalObject).where(ExternalObject.tenant_id == ctx.tenant_id, ExternalObject.object_type == otype)
        )
    )


def _context(ctx: Ctx, kind: str) -> dict:
    out: dict = {"devices": {}, "prefixes_per_vlan": {}, "prefixes_per_vrf": {}}
    if kind == "ip":
        out["devices"] = {
            h.lower(): i
            for i, h in ctx.db.execute(select(Device.id, Device.hostname).where(Device.tenant_id == ctx.tenant_id))
        }
    if kind in ("vlan", "vrf"):
        per_vlan: dict[int, list[str]] = {}
        per_vrf: Counter = Counter()
        for o in _objects(ctx, "prefix"):
            vid = (o.data.get("vlan") or {}).get("id")
            if vid is not None:
                per_vlan.setdefault(vid, []).append(o.data.get("prefix"))
            per_vrf[_name(o.data.get("vrf")) or ""] += 1
        out["prefixes_per_vlan"], out["prefixes_per_vrf"] = per_vlan, per_vrf
    return out


class IpamPage(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int
    synced_at: datetime | None


@router.get("/summary")
def summary(ctx: Ctx = Depends(require("devices:read"))):
    counts = dict(
        ctx.db.execute(
            select(ExternalObject.object_type, func.count())
            .where(ExternalObject.tenant_id == ctx.tenant_id)
            .group_by(ExternalObject.object_type)
        ).all()
    )
    synced = ctx.db.scalar(
        select(func.max(ExternalObject.synced_at)).where(
            ExternalObject.tenant_id == ctx.tenant_id, ExternalObject.source == "netbox"
        )
    )
    prefix_status: Counter = Counter()
    families: Counter = Counter()
    for o in _objects(ctx, "prefix"):
        prefix_status[_choice(o.data.get("status")) or "unknown"] += 1
        families[f"IPv{6 if ':' in str(o.data.get('prefix')) else 4}"] += 1
    ip_status: Counter = Counter(_choice(o.data.get("status")) or "unknown" for o in _objects(ctx, "ip"))
    vlan_sites: Counter = Counter(_site(o.data) or "(no site)" for o in _objects(ctx, "vlan"))
    return {
        "counts": {k: counts.get(v, 0) for k, v in KINDS.items()},
        "synced_at": synced,
        "prefix_status": dict(prefix_status.most_common()),
        "prefix_family": dict(families),
        "ip_status": dict(ip_status.most_common()),
        "vlans_per_site": dict(vlan_sites.most_common(12)),
    }


@router.get("/{kind}", response_model=IpamPage)
def list_objects(
    kind: str,
    q: str | None = None,
    status: str | None = None,
    site: str | None = None,
    vrf: str | None = None,
    device: str | None = None,
    family: int | None = Query(None, ge=4, le=6),
    within: str | None = Query(None, description="only prefixes/IPs inside this CIDR"),
    limit: int = Query(100, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("devices:read")),
):
    otype = KINDS.get(kind)
    if otype is None:
        raise HTTPException(404, f"unknown IPAM object type '{kind}' (one of {', '.join(KINDS)})")
    try:
        parent = ipaddress.ip_network(within, strict=False) if within else None
    except ValueError as e:
        raise HTTPException(422, f"within: {e}") from e
    objs = _objects(ctx, otype)
    context = _context(ctx, otype)
    needle = (q or "").strip().lower()
    rows = []
    synced = None
    for o in objs:
        row = {"id": str(o.id), "netbox_id": o.external_id, "url": _web(o.data), **FLATTEN[otype](o.data, context)}
        synced = max(synced, o.synced_at) if synced else o.synced_at
        if needle and needle not in " ".join(str(v).lower() for v in row.values() if v is not None):
            continue
        if status and (row.get("status") or "") != status:
            continue
        if site and (row.get("site") or "") != site:
            continue
        if vrf is not None and (row.get("vrf") or "") != vrf:
            continue
        if device and (row.get("device") or "").lower() != device.lower():
            continue
        if family and row.get("family") != family:
            continue
        if parent is not None:
            n = _net(row.get("prefix") or row.get("address"))
            if n is None or n.version != parent.version or not n.network.subnet_of(parent):
                continue
        rows.append(row)
    rows.sort(key=lambda r: _sort_key(otype, r))
    return IpamPage(items=rows[offset : offset + limit], total=len(rows), limit=limit, offset=offset, synced_at=synced)
