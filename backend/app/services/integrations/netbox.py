"""Module 14 - NetBox integration (NetBox 3.x/4.x REST API).

Pull: sites, racks, devices, cables (topology), VLANs, prefixes, IP addresses, VRFs, ASNs, contacts.
Push (bidirectional, opt-in via ``options.push_back``): serial number and OS version discovered
during backups are written back to NetBox (``serial`` + custom field ``os_version``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import Device, DeviceModel, ExternalObject, Integration, Link, Platform, Rack, Site, Vendor
from app.services import metrics

log = logging.getLogger(__name__)

PLATFORM_HINTS = [
    ("junos", "junos"),
    ("eos", "eos"),
    ("arista", "eos"),
    ("nxos", "nxos"),
    ("nx-os", "nxos"),
    ("ios", "ios"),
    ("fortios", "fortios"),
    ("forti", "fortios"),
    ("sfos", "sfos"),
    ("sophos", "sfos"),
    ("routeros", "routeros"),
    ("mikrotik", "routeros"),
    ("vyos", "vyos"),
    ("linux", "linux"),
    ("bird", "linux"),
]

MIRRORED = {
    "vlan": "/api/ipam/vlans/",
    "prefix": "/api/ipam/prefixes/",
    "ip": "/api/ipam/ip-addresses/",
    "vrf": "/api/ipam/vrfs/",
    "asn": "/api/ipam/asns/",
    "contact": "/api/tenancy/contacts/",
}


def _fit(value, limit: int):
    """Trim a NetBox string to the portal column size (NetBox limits are usually smaller; this is a guard)."""
    return value[:limit] if isinstance(value, str) else value


def auth_header(token: str) -> str:
    """NetBox < 4.5 and v1 tokens use ``Token <key>``; NetBox 4.5+ v2 tokens (``nbt_<id>.<secret>``)
    must be sent as ``Bearer``. A value pasted with its scheme is used as-is."""
    token = token.strip()
    if token.lower().startswith(("token ", "bearer ")):
        return token
    return f"Bearer {token}" if token.startswith("nbt_") else f"Token {token}"


class NetBoxError(httpx.HTTPStatusError):
    pass


def _v2_secret_only(token: str) -> bool:
    """A NetBox 4.5 v2 token copied without its ``nbt_<key>.`` part looks like a 40-char non-hex string
    (v1 tokens are 40 hex chars)."""
    t = token.strip()
    return len(t) == 40 and t.isalnum() and not all(c in "0123456789abcdef" for c in t)


def _check(r: httpx.Response, token: str = "") -> None:
    """raise_for_status, but carry NetBox's own reason (e.g. "Invalid v1 token") in the message."""
    if r.is_success:
        return
    try:
        detail = r.json().get("detail") or r.text
    except ValueError:
        detail = r.text
    hint = ""
    if r.status_code in (401, 403) and "Invalid v1 token" in str(detail) and _v2_secret_only(token):
        hint = (
            " - this looks like only the secret of a NetBox v2 token: enter it as nbt_<key>.<secret>, where <key>"
            " is the 12-character key shown for the token in NetBox's API token list"
        )
    elif r.status_code in (401, 403):
        hint = (
            " - check the API token: it must be valid, enabled, not expired, allowed from this"
            " server's IP and have read permission on DCIM/IPAM/tenancy objects"
        )
    raise NetBoxError(
        f"NetBox {r.request.method} {r.request.url.path} -> HTTP {r.status_code}: {str(detail)[:300]}{hint}",
        request=r.request,
        response=r,
    )


class NetBoxClient:
    def __init__(self, base_url: str, token: str, verify: bool = True, timeout: float = 30):
        self.token = token
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": auth_header(token), "Accept": "application/json"},
            verify=verify,
            timeout=timeout,
        )

    def paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        url: str | None = path
        p = {"limit": 1000, **(params or {})}
        while url:
            r = self.http.get(url, params=p)
            _check(r, self.token)
            data = r.json()
            yield from data.get("results", [])
            url = data.get("next")
            p = None  # ``next`` already carries the query string

    def patch_device(self, netbox_id: int, payload: dict) -> None:
        _check(self.http.patch(f"/api/dcim/devices/{netbox_id}/", json=payload), self.token)


def map_platform(netbox_platform: dict | None, manufacturer: str | None, mapping: dict[str, str]) -> str | None:
    slug = (netbox_platform or {}).get("slug") or ""
    if slug in mapping:
        return mapping[slug]
    hay = f"{slug} {(netbox_platform or {}).get('name', '')} {manufacturer or ''}".lower()
    for hint, ours in PLATFORM_HINTS:
        if hint in hay:
            return ours
    return None


def _strip_prefix(addr: str | None) -> str | None:
    return addr.split("/")[0] if addr else None


def sync(db: Session, integration: Integration, client: NetBoxClient | None = None) -> dict[str, Any]:
    tenant_id = integration.tenant_id
    opts = integration.options or {}
    client = client or NetBoxClient(
        integration.base_url, decrypt_secret(integration.token_enc) or "", verify=opts.get("verify_tls", True)
    )
    filters = opts.get("filters", {})  # e.g. {"tenant": "decix", "status": "active"}
    stats: dict[str, int] = {}

    # --- sites & racks -----------------------------------------------------
    sites = {
        s.netbox_id: s for s in db.scalars(select(Site).where(Site.tenant_id == tenant_id, Site.netbox_id.is_not(None)))
    }
    for nb in client.paginate("/api/dcim/sites/", filters.get("sites")):
        s = sites.get(nb["id"]) or db.scalar(
            select(Site).where(Site.tenant_id == tenant_id, Site.slug == _fit(nb["slug"], 128))
        )
        if s is None:
            s = Site(tenant_id=tenant_id, slug=_fit(nb["slug"], 128), name=_fit(nb["name"], 255))
            db.add(s)
        s.name, s.slug, s.netbox_id = _fit(nb["name"], 255), _fit(nb["slug"], 128), nb["id"]
        s.address = nb.get("physical_address") or s.address
        s.latitude, s.longitude = nb.get("latitude"), nb.get("longitude")
        sites[nb["id"]] = s
    db.flush()
    stats["sites"] = len(sites)

    racks = {
        r.netbox_id: r for r in db.scalars(select(Rack).where(Rack.tenant_id == tenant_id, Rack.netbox_id.is_not(None)))
    }
    for nb in client.paginate("/api/dcim/racks/", filters.get("racks")):
        site = sites.get((nb.get("site") or {}).get("id"))
        if site is None:
            continue
        r = racks.get(nb["id"])
        if r is None:
            r = Rack(tenant_id=tenant_id, site_id=site.id, name=_fit(nb["name"], 255), netbox_id=nb["id"])
            db.add(r)
        r.name, r.site_id, r.u_height = _fit(nb["name"], 255), site.id, int(nb.get("u_height") or 42)
        racks[nb["id"]] = r
    db.flush()
    stats["racks"] = len(racks)

    # --- devices -----------------------------------------------------------
    platforms = {p.slug: p for p in db.scalars(select(Platform))}
    vendors = {v.slug: v for v in db.scalars(select(Vendor))}
    by_nb = {
        d.netbox_id: d
        for d in db.scalars(select(Device).where(Device.tenant_id == tenant_id, Device.netbox_id.is_not(None)))
    }
    by_name = {d.hostname: d for d in db.scalars(select(Device).where(Device.tenant_id == tenant_id))}
    seen = 0
    no_ip: list[str] = []
    unnamed = 0
    for nb in client.paginate("/api/dcim/devices/", filters.get("devices")):
        if not nb.get("name"):
            unnamed += 1  # NetBox allows unnamed devices (e.g. patch panels); nothing to manage
            continue
        ip = _strip_prefix(
            (
                nb.get("primary_ip4")
                or nb.get("primary_ip6")
                or nb.get("primary_ip")
                or nb.get("oob_ip")  # NetBox 4 out-of-band management address
                or {}
            ).get("address")
        )
        if not ip:
            no_ip.append(nb["name"])
        manu = (nb.get("device_type") or {}).get("manufacturer") or {}
        vendor = vendors.get(manu.get("slug", ""))
        if vendor is None and manu.get("slug"):
            vendor = Vendor(slug=_fit(manu["slug"], 128), name=_fit(manu.get("name") or manu["slug"], 128))
            db.add(vendor)
            db.flush()
            vendors[vendor.slug] = vendor
        d = by_nb.get(nb["id"]) or by_name.get(nb["name"])
        if d is None:
            # Devices without an address are imported for inventory/topology; backups stay off until
            # NetBox gets a primary or OOB IP for them.
            d = Device(
                tenant_id=tenant_id, hostname=_fit(nb["name"], 128), management_ip=ip or "", backup_enabled=bool(ip)
            )
            db.add(d)
        elif ip and not d.management_ip:
            d.backup_enabled = True  # address assigned in NetBox since the last sync
        d.hostname, d.netbox_id = _fit(nb["name"], 128), nb["id"]
        d.management_ip = ip or d.management_ip or ""
        d.site_id = sites[nb["site"]["id"]].id if nb.get("site") and nb["site"]["id"] in sites else d.site_id
        d.rack_id = racks[nb["rack"]["id"]].id if nb.get("rack") and nb["rack"]["id"] in racks else None
        d.vendor_id = vendor.id if vendor else d.vendor_id
        pslug = map_platform(nb.get("platform"), manu.get("slug"), opts.get("platform_map", {}))
        if pslug and pslug in platforms:
            d.platform_id = platforms[pslug].id
        model_name = _fit((nb.get("device_type") or {}).get("model"), 255)
        if model_name and vendor:
            m = db.scalar(select(DeviceModel).where(DeviceModel.vendor_id == vendor.id, DeviceModel.name == model_name))
            if m is None:
                m = DeviceModel(vendor_id=vendor.id, name=model_name)
                db.add(m)
                db.flush()
            d.model_id = m.id
        d.serial = _fit(nb.get("serial"), 128) or d.serial
        role = nb.get("role") or nb.get("device_role") or {}
        d.role = _fit(role.get("slug"), 128) or d.role
        status = (nb.get("status") or {}).get("value", "active")
        d.status = status if status in ("active", "planned", "offline", "decommissioning") else "active"
        d.tags = [t["slug"] for t in nb.get("tags", [])]
        d.custom_fields = nb.get("custom_fields") or {}
        by_nb[nb["id"]] = d
        seen += 1
    db.flush()
    stats["devices"] = seen
    stats["devices_without_ip"] = len(no_ip)
    stats["devices_unnamed_skipped"] = unnamed
    stats["devices_without_platform"] = sum(1 for d in by_nb.values() if d.platform_id is None)
    if no_ip:
        stats["devices_without_ip_examples"] = sorted(no_ip)[:20]

    # --- cables -> links (topology) ----------------------------------------
    if opts.get("sync_cables", True):
        name_to_dev = {d.hostname: d for d in by_nb.values()}
        existing = {
            (lk.a_device_id, lk.a_interface, lk.b_device_id, lk.b_interface): lk
            for lk in db.scalars(select(Link).where(Link.tenant_id == tenant_id, Link.source == "netbox"))
        }
        keep = set()
        for cable in client.paginate("/api/dcim/cables/", filters.get("cables")):
            a = (cable.get("a_terminations") or [{}])[0].get("object") or {}
            b = (cable.get("b_terminations") or [{}])[0].get("object") or {}
            da = name_to_dev.get((a.get("device") or {}).get("name"))
            dbv = name_to_dev.get((b.get("device") or {}).get("name"))
            if not da or not dbv:
                continue
            key = (da.id, _fit(a.get("name", "?"), 128), dbv.id, _fit(b.get("name", "?"), 128))
            if key not in existing:
                existing[key] = Link(
                    tenant_id=tenant_id,
                    a_device_id=da.id,
                    a_interface=key[1],
                    b_device_id=dbv.id,
                    b_interface=key[3],
                    source="netbox",
                )
                db.add(existing[key])
            existing[key].status = "up" if (cable.get("status") or {}).get("value") == "connected" else "planned"
            keep.add(key)
        for key, link in existing.items():
            if key not in keep:
                db.delete(link)
        stats["links"] = len(keep)

    # --- IPAM / tenancy mirror ---------------------------------------------
    for otype, path in MIRRORED.items():
        if otype not in opts.get("mirror", list(MIRRORED)):
            continue
        existing_rows = {
            row.external_id: row
            for row in db.scalars(
                select(ExternalObject).where(
                    ExternalObject.tenant_id == tenant_id,
                    ExternalObject.source == "netbox",
                    ExternalObject.object_type == otype,
                )
            )
        }
        seen_ids: set[str] = set()
        now = utcnow()
        for nb in client.paginate(path, filters.get(otype)):
            eid = str(nb["id"])
            row = existing_rows.get(eid)
            if row is None:
                row = ExternalObject(tenant_id=tenant_id, source="netbox", object_type=otype, external_id=eid)
                db.add(row)
                existing_rows[eid] = row
            row.display = str(nb.get("display") or nb.get("name") or nb.get("prefix") or nb.get("address") or eid)[:255]
            row.data = nb
            row.synced_at = now
            seen_ids.add(eid)
        removed = 0
        for eid, row in existing_rows.items():
            if eid not in seen_ids:  # deleted in NetBox (or no longer matching the filter)
                db.delete(row)
                removed += 1
        stats[otype] = len(seen_ids)
        if removed:
            stats[f"{otype}_removed"] = removed
        db.flush()

    # --- push back ---------------------------------------------------------
    if opts.get("push_back"):
        pushed = 0
        for d in by_nb.values():
            if d.os_version and d.custom_fields.get("os_version") != d.os_version:
                try:
                    client.patch_device(d.netbox_id, {"custom_fields": {"os_version": d.os_version}})
                    pushed += 1
                except httpx.HTTPError:
                    log.warning("push-back to NetBox failed for %s", d.hostname, exc_info=True)
        stats["pushed"] = pushed

    integration.last_sync_at = utcnow()
    integration.last_sync_status = "success"
    integration.last_sync_detail = stats
    metrics.SYNC_RUNS.labels(kind="netbox", status="success").inc()
    db.flush()
    return stats
