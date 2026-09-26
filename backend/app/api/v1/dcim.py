"""DCIM view of a device: front-panel ports from the device type, populated from the stored config.

``GET /devices/{id}/ports`` joins three sources:

* the device type (NetBox devicetype-library) -> which ports the chassis has and their form factor;
* the latest backed-up configuration -> description, admin state, LAG, VLANs, addresses, protocols;
* the rest of the inventory -> what is on the other end: NetBox cables, the device owning the
  other address of a point-to-point subnet, BGP neighbours on the port's subnets (with the IXP
  member behind the ASN), and devices / ASNs named in the description.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import Ctx, require
from app.api.v1.configs import _device
from app.models import Device, IxpMember, Link, RancidConfig, Tenant
from app.services import audit
from app.services.backup.engine import device_relpath, store_for
from app.services.dcim import devicetypes, ports, topology
from app.services.intel.parser import parse as parse_intel

router = APIRouter(tags=["dcim"])

OVERRIDES_KEY = "device_types"
MAX_BGP_PER_PORT = 200

# --- helpers ----------------------------------------------------------------------------------


def form_factor(ptype: str | None, name: str) -> str:
    t = (ptype or "").lower()
    if "qsfp-dd" in t or "qsfpdd" in t:
        return "qsfpdd"
    if "qsfp" in t or "cfp" in t:
        return "qsfp"
    if "sfp" in t or t.endswith("-x") or "base-x" in t:
        return "sfp"
    if "base-t" in t or t in ("1000base-t", "100base-tx"):
        return "rj45"
    if t.startswith("virtual") or t == "lag":
        return "virtual"
    n = name.lower()
    if n.startswith("et-"):
        return "qsfp"
    if n.startswith(("xe-", "ge-")) or n.startswith("ethernet"):
        return "sfp"
    if n.startswith(("fxp", "em", "me", "management", "mgmt")) or "gigabitethernet0" == n:
        return "rj45"
    return "sfp"


def speed_label(ptype: str | None, name: str) -> str | None:
    t = (ptype or "").lower()
    m = re.match(r"^(\d+(?:\.\d+)?)(g?)base", t)
    if m:
        n = float(m.group(1))
        if m.group(2):
            return f"{m.group(1)}G"
        return f"{int(n // 1000)}G" if n >= 1000 else f"{int(n)}M"
    n = name.lower()
    for prefix, lbl in (("et-", "100G"), ("xe-", "10G"), ("ge-", "1G"), ("mge-", "10G"), ("hundredgig", "100G")):
        if n.startswith(prefix):
            return lbl
    if n.startswith(("tengig", "te")):
        return "10G"
    if n.startswith(("gigabit", "gi")):
        return "1G"
    return None


def _model_hint(ctx: Ctx, d: Device) -> str | None:
    """Model from RANCID's header (``# Chassis ... MX204`` / ``!Chassis type: ISR4451-X/K9`` / ``!Model:``)."""
    rc = ctx.db.scalar(select(RancidConfig).where(RancidConfig.device_id == d.id).limit(1))
    if rc is None:
        return None
    for line in rc.content.splitlines()[:120]:
        if m := re.match(r"^[#!]\s*Chassis type:\s*(\S+)", line):
            return m.group(1).split("/")[0]
        if m := re.match(r"^[#!]\s*Model:\s*(\S+)", line, re.I):
            return m.group(1)
        if m := re.match(r"^#\s*Chassis\s+.*?\s(\S+)\s*$", line):
            return m.group(1)
    return None


def _override(ctx: Ctx, d: Device) -> dict | None:
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    return ((tenant.settings or {}).get(OVERRIDES_KEY) or {}).get(str(d.id)) if tenant else None


def _device_type(ctx: Ctx, d: Device) -> tuple[devicetypes.DeviceType | None, dict]:
    ov = _override(ctx, d) or {}
    vendor_slug = ov.get("vendor") or (d.vendor.slug if d.vendor else None)
    vendor_name = d.vendor.name if d.vendor else None
    model = ov.get("model") or (d.model.name if d.model else None)
    source = "override" if ov.get("model") else "inventory" if model else None
    if not model:
        model = _model_hint(ctx, d)
        source = "rancid" if model else None
    dt = devicetypes.resolve(vendor_slug, vendor_name, model) if model else None
    return dt, {"model": model, "vendor": vendor_slug, "model_source": source}


def _addresses_by_device(ctx: Ctx, devices: dict[uuid.UUID, Device]) -> dict[uuid.UUID, list[tuple[Any, str]]]:
    """device -> [(ip_interface, interface name)] from each device's latest config."""
    out = {}
    for did, ifs in topology.parsed_interfaces(ctx.db, ctx.tenant_id, devices).items():
        addrs = []
        for i in ifs.values():
            for u in i.units.values():
                for a in u.addresses:
                    try:
                        addrs.append((ipaddress.ip_interface(a), i.name if u.name == "0" else f"{i.name}.{u.name}"))
                    except ValueError:
                        continue
        out[did] = addrs
    return out


def _is_p2p(net) -> bool:
    return (net.version == 4 and net.prefixlen >= 29) or (net.version == 6 and net.prefixlen >= 112)


# --- endpoint -----------------------------------------------------------------------------------


@router.get("/devices/{device_id}/ports")
def device_ports(device_id: uuid.UUID, ctx: Ctx = Depends(require("configs:read"))):
    d = _device(ctx, device_id)
    plat = d.platform.slug if d.platform else None
    store = store_for(ctx.db, ctx.tenant_id)
    config = store.read(device_relpath(d)) or ""
    ifs = ports.parse(config, plat)
    dt, model_info = _device_type(ctx, d)

    # --- inventory context
    devices = {
        x.id: x
        for x in ctx.db.scalars(
            select(Device).where(Device.tenant_id == ctx.tenant_id).options(selectinload(Device.platform))
        )
    }
    names = {}
    for x in devices.values():
        if x.id != d.id and len(x.hostname) >= 4:
            names[x.hostname.lower()] = x
            names.setdefault(x.hostname.lower().split(".")[0], x)
    name_re = (
        re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w-])", re.I
        )
        if names
        else None
    )
    members = {m.asn: m.name for m in ctx.db.scalars(select(IxpMember).where(IxpMember.tenant_id == ctx.tenant_id))}
    addr_map = _addresses_by_device(ctx, devices)
    ip_owner: dict[str, tuple[uuid.UUID, str]] = {}
    for did, addrs in addr_map.items():
        if did == d.id:
            continue
        for ipi, ifname in addrs:
            ip_owner[str(ipi.ip)] = (did, ifname)
    bgp = [o for o in parse_intel(config, plat or "") if o.kind == "bgp_neighbor"]
    cables: dict[str, list[dict]] = {}
    for lk in ctx.db.scalars(select(Link).where(Link.tenant_id == ctx.tenant_id)):
        if lk.a_device_id == d.id:
            peer_id, peer_if, mine = lk.b_device_id, lk.b_interface, lk.a_interface
        elif lk.b_device_id == d.id:
            peer_id, peer_if, mine = lk.a_device_id, lk.a_interface, lk.b_interface
        else:
            continue
        peer = devices.get(peer_id)
        if peer:
            cables.setdefault(mine, []).append(
                {
                    "kind": "device",
                    "source": "cable",
                    "device_id": str(peer.id),
                    "hostname": peer.hostname,
                    "interface": peer_if,
                }
            )

    def device_peer(did: uuid.UUID, iface: str | None, source: str) -> dict:
        x = devices[did]
        return {"kind": "device", "source": source, "device_id": str(x.id), "hostname": x.hostname, "interface": iface}

    def peers_for(i: ports.Interface) -> tuple[list[dict], int]:
        found: list[dict] = list(cables.get(i.name, []))
        bgp_total = 0
        for u in i.units.values():
            for a in u.addresses:
                try:
                    net = ipaddress.ip_interface(a).network
                except ValueError:
                    continue
                if _is_p2p(net):
                    for ip, (did, ifname) in ip_owner.items():
                        try:
                            if ipaddress.ip_address(ip) in net:
                                found.append({**device_peer(did, ifname, "subnet"), "address": ip})
                        except ValueError:
                            continue
                for o in bgp:
                    try:
                        if ipaddress.ip_address(o.key) not in net:
                            continue
                    except ValueError:
                        continue
                    bgp_total += 1
                    if bgp_total > MAX_BGP_PER_PORT:
                        continue
                    asn = o.attributes.get("peer_as")
                    owner = ip_owner.get(o.key)
                    found.append(
                        {
                            "kind": "bgp",
                            "source": "bgp",
                            "address": o.key,
                            "asn": asn,
                            "name": members.get(asn) or o.attributes.get("description"),
                            "group": o.attributes.get("group"),
                            "unit": u.name,
                            **({"device_id": str(owner[0]), "hostname": devices[owner[0]].hostname} if owner else {}),
                        }
                    )
        texts = [i.description or ""] + [u.description or "" for u in i.units.values()]
        for t in texts:
            if name_re:
                for m in name_re.finditer(t):
                    x = names[m.group(1).lower()]
                    found.append({**device_peer(x.id, None, "description")})
            for m in re.finditer(r"\bAS\s?(\d{1,10})\b", t, re.I):
                asn = int(m.group(1))
                found.append({"kind": "asn", "source": "description", "asn": asn, "name": members.get(asn)})
        # de-duplicate: a cable/subnet match beats a description mention of the same device
        rank = {"cable": 0, "subnet": 1, "bgp": 2, "description": 3}
        seen: dict[tuple, dict] = {}
        for p in sorted(found, key=lambda p: rank.get(p["source"], 9)):
            key = (p["kind"], p.get("device_id") or p.get("address") or p.get("asn"))
            if p["kind"] == "asn" and any(q.get("asn") == p["asn"] for q in seen.values()):
                continue
            seen.setdefault(key, p)
        return list(seen.values()), bgp_total

    # --- LAGs
    lag_members: dict[str, list[str]] = {}
    for i in ifs.values():
        if i.lag:
            lag_members.setdefault(i.lag, []).append(i.name)
    iface_out: dict[str, dict] = {}
    for i in ifs.values():
        dct = i.to_dict()
        dct["peers"], dct["bgp_total"] = peers_for(i)
        iface_out[i.name] = dct
    for lag, mem in lag_members.items():
        lag_peers = iface_out.get(lag, {}).get("peers", [])
        for mname in mem:
            iface_out[mname]["lag_peers"] = lag_peers

    # --- ports: device-type template, else physical interfaces from the config
    by_key: dict[str, list[str]] = {}
    for name in ifs:
        if not ports.is_virtual(name) and not ifs[name].is_lag:
            by_key.setdefault(ports.port_key(name), []).append(name)
    template = [i for i in (dt.interfaces if dt else []) if (i.get("type") or "") not in ("virtual", "lag")]
    out_ports = []
    used: set[str] = set()
    for t in template:
        names_ = sorted(set([t["name"]] if t["name"] in ifs else []) | set(by_key.get(ports.port_key(t["name"]), [])))
        used.update(names_)
        out_ports.append(_port(t["name"], t.get("type"), t.get("mgmt_only", False), names_, iface_out, True))
    extra = [n for key, ns in by_key.items() for n in ns if n not in used]
    if not template:
        groups: dict[str, list[str]] = {}
        for n in extra:
            groups.setdefault(n.split(":")[0], []).append(n)
        for parent in sorted(groups, key=_natural):
            out_ports.append(
                _port(
                    parent,
                    None,
                    parent.startswith(("fxp", "em", "me0", "mgmt", "Management")),
                    sorted(groups[parent]),
                    iface_out,
                    False,
                )
            )
        extra = []
    lags = [
        {**iface_out.get(lag, {"name": lag, "units": [], "peers": []}), "members": sorted(mem, key=_natural)}
        for lag, mem in sorted(lag_members.items(), key=lambda kv: _natural(kv[0]))
    ]
    logical = [iface_out[n] for n in sorted(ifs, key=_natural) if ports.is_virtual(n) and iface_out[n]["units"]]
    summary = {
        "ports": len(out_ports),
        "configured": sum(1 for p in out_ports if p["state"] not in ("unused",)),
        "up": sum(1 for p in out_ports if p["state"] in ("up", "lag")),
        "disabled": sum(1 for p in out_ports if p["state"] == "disabled"),
        "unused": sum(1 for p in out_ports if p["state"] == "unused"),
        "lags": len(lags),
        "peers": len({(p.get("device_id") or p.get("asn") or p.get("address")) for x in out_ports for p in x["peers"]}),
    }
    return {
        "device": {
            "id": str(d.id),
            "hostname": d.hostname,
            "vendor": d.vendor.name if d.vendor else None,
            "platform": plat,
        },
        "device_type": dt.to_dict() if dt else None,
        **model_info,
        "has_config": bool(config),
        "ports": out_ports,
        "unmatched": [iface_out[n] for n in sorted(extra, key=_natural)],
        "lags": lags,
        "logical": logical,
        "summary": summary,
    }


def _natural(s: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def _port(
    name: str, ptype: str | None, mgmt: bool, config_names: list[str], iface_out: dict, in_template: bool
) -> dict:
    ifaces = [iface_out[n] for n in config_names]
    peers: list[dict] = []
    for i in ifaces:
        peers += i.get("peers", []) + i.get("lag_peers", [])
    configured = [i for i in ifaces if i["description"] or i["units"] or i["lag"] or i["disabled"] or i["mtu"]]
    if not configured:
        state = "unused"
    elif all(i["disabled"] or i["inactive"] for i in configured):
        state = "disabled"
    elif any(i["lag"] for i in configured):
        state = "lag"
    else:
        state = "up"
    main = ifaces[0] if ifaces else None
    return {
        "name": name,
        "type": ptype,
        "form": form_factor(ptype, name),
        "speed": speed_label(ptype, name),
        "mgmt": mgmt,
        "in_template": in_template,
        "state": state,
        "description": next((i["description"] for i in ifaces if i["description"]), None),
        "lag": next((i["lag"] for i in ifaces if i["lag"]), None),
        "channels": [i["name"] for i in ifaces if i["name"] != name],
        "interfaces": ifaces,
        "peers": _dedupe(peers),
        "bgp_total": sum(i.get("bgp_total", 0) for i in ifaces),
        "config_name": main["name"] if main else None,
    }


def _dedupe(peers: list[dict]) -> list[dict]:
    out, seen = [], set()
    for p in peers:
        k = (p["kind"], p.get("device_id"), p.get("address"), p.get("asn"), p.get("interface"))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


@router.get("/devices/{device_id}/front-image")
def device_front_image(device_id: uuid.UUID, ctx: Ctx = Depends(require("configs:read"))):
    """Front-panel photo from the devicetype-library (proxied and cached so browsers need no internet)."""
    d = _device(ctx, device_id)
    dt, _ = _device_type(ctx, d)
    img = devicetypes.front_image(dt) if dt else None
    if img is None:
        raise HTTPException(404, "no front image for this device type")
    return Response(img[0], media_type=img[1], headers={"Cache-Control": "private, max-age=86400"})


class DeviceTypeIn(BaseModel):
    model: str
    vendor: str | None = None  # NOM vendor slug, defaults to the device's vendor


@router.put("/devices/{device_id}/device-type")
def set_device_type(device_id: uuid.UUID, body: DeviceTypeIn, ctx: Ctx = Depends(require("devices:write"))):
    """Pin the device-type model for the port view (when NetBox has none or a different name)."""
    d = _device(ctx, device_id, "devices:read")
    vendor = body.vendor or (d.vendor.slug if d.vendor else None)
    dt = devicetypes.resolve(vendor, d.vendor.name if d.vendor else None, body.model.strip())
    if dt is None:
        raise HTTPException(422, f"'{body.model}' not found in the device type library")
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    settings = dict(tenant.settings or {})
    ov = dict(settings.get(OVERRIDES_KEY) or {})
    ov[str(d.id)] = {"model": dt.model, "vendor": vendor}
    settings[OVERRIDES_KEY] = ov
    tenant.settings = settings
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device.device_type",
        actor=ctx.user,
        target_type="device",
        target_id=d.id,
        target_name=d.hostname,
        after={"model": dt.model, "vendor": vendor},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return dt.to_dict()


@router.delete("/devices/{device_id}/device-type", status_code=204)
def clear_device_type(device_id: uuid.UUID, ctx: Ctx = Depends(require("devices:write"))):
    d = _device(ctx, device_id, "devices:read")
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    settings = dict(tenant.settings or {})
    ov = dict(settings.get(OVERRIDES_KEY) or {})
    if ov.pop(str(d.id), None) is not None:
        settings[OVERRIDES_KEY] = ov
        tenant.settings = settings
        ctx.db.commit()
