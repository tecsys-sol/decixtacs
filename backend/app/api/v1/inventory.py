"""Module 3 (inventory), 12 (device groups), 13 (network map)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import Ctx, get_owned, require
from app.api.v1.common import ORM, Page, paginate
from app.core.security import encrypt_secret
from app.db.base import utcnow
from app.models import Credential, Device, DeviceGroup, Link, Platform, Rack, Region, Site, Vendor
from app.services import audit
from app.services.audit import model_snapshot

router = APIRouter(tags=["inventory"])

DEVICE_FIELDS = [
    "hostname",
    "management_ip",
    "site_id",
    "platform_id",
    "vendor_id",
    "role",
    "status",
    "backup_enabled",
    "credential_id",
    "serial",
    "os_version",
    "tags",
]


# --- sites / regions / racks ----------------------------------------------------------


class SiteIn(BaseModel):
    name: str
    slug: str
    kind: str = "pop"
    region_id: uuid.UUID | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class SiteOut(SiteIn, ORM):
    id: uuid.UUID
    netbox_id: int | None
    device_count: int = 0


class RegionIn(BaseModel):
    name: str
    slug: str


class RegionOut(RegionIn, ORM):
    id: uuid.UUID


class RackIn(BaseModel):
    name: str
    site_id: uuid.UUID
    u_height: int = 42


class RackOut(RackIn, ORM):
    id: uuid.UUID


@router.get("/regions", response_model=list[RegionOut])
def list_regions(ctx: Ctx = Depends(require("devices:read"))):
    return ctx.db.scalars(select(Region).where(Region.tenant_id == ctx.tenant_id).order_by(Region.name)).all()


@router.post("/regions", response_model=RegionOut, status_code=201)
def create_region(body: RegionIn, ctx: Ctx = Depends(require("devices:write"))):
    r = Region(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.commit()
    return r


@router.get("/sites", response_model=list[SiteOut])
def list_sites(ctx: Ctx = Depends(require("devices:read"))):
    counts = dict(
        ctx.db.execute(
            select(Device.site_id, func.count()).where(Device.tenant_id == ctx.tenant_id).group_by(Device.site_id)
        ).all()
    )
    out = []
    for s in ctx.db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id).order_by(Site.name)):
        o = SiteOut.model_validate(s)
        o.device_count = counts.get(s.id, 0)
        out.append(o)
    return out


@router.post("/sites", response_model=SiteOut, status_code=201)
def create_site(body: SiteIn, ctx: Ctx = Depends(require("devices:write"))):
    s = Site(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="site.create",
        actor=ctx.user,
        target_type="site",
        target_id=s.id,
        target_name=s.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return s


@router.patch("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: uuid.UUID, body: SiteIn, ctx: Ctx = Depends(require("devices:write"))):
    s = get_owned(ctx, Site, site_id, "site")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="site.update",
        actor=ctx.user,
        target_type="site",
        target_id=s.id,
        target_name=s.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return s


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(site_id: uuid.UUID, ctx: Ctx = Depends(require("devices:write"))):
    s = get_owned(ctx, Site, site_id, "site")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="site.delete",
        actor=ctx.user,
        target_type="site",
        target_id=s.id,
        target_name=s.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(s)
    ctx.db.commit()


@router.get("/racks", response_model=list[RackOut])
def list_racks(site_id: uuid.UUID | None = None, ctx: Ctx = Depends(require("devices:read"))):
    stmt = select(Rack).where(Rack.tenant_id == ctx.tenant_id).order_by(Rack.name)
    if site_id:
        stmt = stmt.where(Rack.site_id == site_id)
    return ctx.db.scalars(stmt).all()


@router.post("/racks", response_model=RackOut, status_code=201)
def create_rack(body: RackIn, ctx: Ctx = Depends(require("devices:write"))):
    get_owned(ctx, Site, body.site_id, "site")
    r = Rack(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.commit()
    return r


# --- vendors / platforms (global catalogue) ----------------------------------------------


class VendorOut(ORM):
    id: uuid.UUID
    name: str
    slug: str


class PlatformOut(ORM):
    id: uuid.UUID
    slug: str
    name: str
    scrapli_platform: str | None
    netmiko_device_type: str | None
    backup_commands: list[str]
    tacacs_service: str
    supports_tacacs: bool
    supports_config_replace: bool


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(ctx: Ctx = Depends(require("devices:read"))):
    return ctx.db.scalars(select(Vendor).order_by(Vendor.name)).all()


@router.get("/platforms", response_model=list[PlatformOut])
def list_platforms(ctx: Ctx = Depends(require("devices:read"))):
    return ctx.db.scalars(select(Platform).order_by(Platform.name)).all()


# --- credentials -----------------------------------------------------------------------


class CredentialIn(BaseModel):
    name: str
    username: str
    password: str | None = None
    ssh_key: str | None = None
    enable_secret: str | None = None


class CredentialOut(ORM):
    id: uuid.UUID
    name: str
    username: str
    has_password: bool = False
    has_ssh_key: bool = False
    rotated_at: datetime | None


def _cred_out(c: Credential) -> CredentialOut:
    o = CredentialOut.model_validate(c)
    o.has_password, o.has_ssh_key = bool(c.password_enc), bool(c.ssh_key_enc)
    return o


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(ctx: Ctx = Depends(require("devices:read"))):
    return [_cred_out(c) for c in ctx.db.scalars(select(Credential).where(Credential.tenant_id == ctx.tenant_id))]


@router.post("/credentials", response_model=CredentialOut, status_code=201)
def create_credential(body: CredentialIn, ctx: Ctx = Depends(require("credentials:write"))):
    c = Credential(
        tenant_id=ctx.tenant_id,
        name=body.name,
        username=body.username,
        password_enc=encrypt_secret(body.password),
        ssh_key_enc=encrypt_secret(body.ssh_key),
        enable_secret_enc=encrypt_secret(body.enable_secret),
        rotated_at=utcnow(),
    )
    ctx.db.add(c)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="credential.create",
        actor=ctx.user,
        target_type="credential",
        target_id=c.id,
        target_name=c.name,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return _cred_out(c)


@router.put("/credentials/{cred_id}", response_model=CredentialOut)
def rotate_credential(cred_id: uuid.UUID, body: CredentialIn, ctx: Ctx = Depends(require("credentials:write"))):
    c = get_owned(ctx, Credential, cred_id, "credential")
    c.name, c.username = body.name, body.username
    if body.password is not None:
        c.password_enc = encrypt_secret(body.password)
    if body.ssh_key is not None:
        c.ssh_key_enc = encrypt_secret(body.ssh_key)
    if body.enable_secret is not None:
        c.enable_secret_enc = encrypt_secret(body.enable_secret)
    c.rotated_at = utcnow()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="credential.rotate",
        actor=ctx.user,
        target_type="credential",
        target_id=c.id,
        target_name=c.name,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return _cred_out(c)


# --- devices ---------------------------------------------------------------------------


class DeviceIn(BaseModel):
    hostname: str
    management_ip: str
    site_id: uuid.UUID | None = None
    rack_id: uuid.UUID | None = None
    platform_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    credential_id: uuid.UUID | None = None
    serial: str | None = None
    os_version: str | None = None
    role: str | None = None
    status: str = "active"
    backup_enabled: bool = True
    ssh_port: int = 22
    tags: list[str] = []
    group_ids: list[uuid.UUID] = []


class DevicePatch(BaseModel):
    hostname: str | None = None
    management_ip: str | None = None
    site_id: uuid.UUID | None = None
    platform_id: uuid.UUID | None = None
    credential_id: uuid.UUID | None = None
    role: str | None = None
    status: str | None = None
    backup_enabled: bool | None = None
    ssh_port: int | None = None
    tags: list[str] | None = None
    group_ids: list[uuid.UUID] | None = None


class Ref(ORM):
    id: uuid.UUID
    name: str


class PlatformRef(ORM):
    id: uuid.UUID
    slug: str
    name: str


class DeviceOut(ORM):
    id: uuid.UUID
    hostname: str
    management_ip: str
    site: Ref | None
    platform: PlatformRef | None
    vendor: Ref | None
    serial: str | None
    os_version: str | None
    role: str | None
    status: str
    reachability: str
    backup_enabled: bool
    ssh_port: int
    tags: list[str]
    netbox_id: int | None
    credential_id: uuid.UUID | None
    last_backup_at: datetime | None
    last_backup_status: str | None
    groups: list[Ref] = []
    created_at: datetime


def _device_query(ctx: Ctx):
    return (
        select(Device)
        .where(Device.tenant_id == ctx.tenant_id)
        .options(
            selectinload(Device.site),
            selectinload(Device.platform),
            selectinload(Device.vendor),
            selectinload(Device.groups),
        )
    )


def visible_devices_filter(ctx: Ctx, stmt, permission: str = "devices:read"):
    """ABAC: users with only scoped grants see only devices inside their sites / device groups."""
    if ctx.principal.has_global(permission):
        return stmt
    site_ids = [g.scope_id for g in ctx.principal.grants if g.permission == permission and g.scope_type == "site"]
    group_ids = [
        g.scope_id for g in ctx.principal.grants if g.permission == permission and g.scope_type == "device_group"
    ]
    conds = []
    if site_ids:
        conds.append(Device.site_id.in_(site_ids))
    if group_ids:
        conds.append(Device.groups.any(DeviceGroup.id.in_(group_ids)))
    return stmt.where(or_(*conds)) if conds else stmt.where(false())


@router.get("/devices", response_model=Page[DeviceOut])
def list_devices(
    q: str | None = None,
    site_id: uuid.UUID | None = None,
    platform: str | None = None,
    vendor: str | None = None,
    role: str | None = None,
    status: str | None = None,
    group_id: uuid.UUID | None = None,
    backup_status: str | None = None,
    limit: int = Query(50, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("devices:read")),
):
    stmt = visible_devices_filter(ctx, _device_query(ctx)).order_by(Device.hostname)
    if q:
        stmt = stmt.where(
            or_(Device.hostname.ilike(f"%{q}%"), Device.management_ip.ilike(f"{q}%"), Device.serial.ilike(f"%{q}%"))
        )
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    if platform:
        stmt = stmt.where(Device.platform.has(Platform.slug == platform))
    if vendor:
        stmt = stmt.where(Device.vendor.has(Vendor.slug == vendor))
    if role:
        stmt = stmt.where(Device.role == role)
    if status:
        stmt = stmt.where(Device.status == status)
    if group_id:
        stmt = stmt.where(Device.groups.any(DeviceGroup.id == group_id))
    if backup_status:
        stmt = stmt.where(Device.last_backup_status == backup_status)
    return paginate(ctx.db, stmt, DeviceOut, limit, offset)


def _device_groups(ctx: Ctx, ids: list[uuid.UUID]) -> list[DeviceGroup]:
    groups = list(
        ctx.db.scalars(select(DeviceGroup).where(DeviceGroup.tenant_id == ctx.tenant_id, DeviceGroup.id.in_(ids)))
    )
    if len(groups) != len(set(ids)):
        raise HTTPException(422, "unknown device group")
    return groups


def _check_refs(ctx: Ctx, site_id=None, credential_id=None):
    if site_id:
        get_owned(ctx, Site, site_id, "site")
    if credential_id:
        get_owned(ctx, Credential, credential_id, "credential")


@router.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(body: DeviceIn, ctx: Ctx = Depends(require("devices:write"))):
    if ctx.db.scalar(select(Device.id).where(Device.tenant_id == ctx.tenant_id, Device.hostname == body.hostname)):
        raise HTTPException(409, "hostname already exists")
    _check_refs(ctx, body.site_id, body.credential_id)
    data = body.model_dump(exclude={"group_ids"})
    d = Device(tenant_id=ctx.tenant_id, **data)
    if d.platform_id and not d.vendor_id:
        p = ctx.db.get(Platform, d.platform_id)
        d.vendor_id = p.vendor_id if p else None
    d.groups = _device_groups(ctx, body.group_ids)
    ctx.db.add(d)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device.create",
        actor=ctx.user,
        target_type="device",
        target_id=d.id,
        target_name=d.hostname,
        after=model_snapshot(d, DEVICE_FIELDS),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return ctx.db.scalar(_device_query(ctx).where(Device.id == d.id))


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: uuid.UUID, ctx: Ctx = Depends(require("devices:read"))):
    d = get_owned(ctx, Device, device_id, "device")
    if not ctx.principal.can_on_device("devices:read", d):
        raise HTTPException(404, "device not found")
    return d


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(device_id: uuid.UUID, body: DevicePatch, ctx: Ctx = Depends(require("devices:write"))):
    d = get_owned(ctx, Device, device_id, "device")
    if not ctx.principal.can_on_device("devices:write", d):
        raise HTTPException(403, "not allowed on this device")
    before = model_snapshot(d, DEVICE_FIELDS)
    data = body.model_dump(exclude_unset=True, exclude={"group_ids"})
    _check_refs(ctx, data.get("site_id"), data.get("credential_id"))
    for k, v in data.items():
        setattr(d, k, v)
    if body.group_ids is not None:
        d.groups = _device_groups(ctx, body.group_ids)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device.update",
        actor=ctx.user,
        target_type="device",
        target_id=d.id,
        target_name=d.hostname,
        before=before,
        after=model_snapshot(d, DEVICE_FIELDS),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return d


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: uuid.UUID, ctx: Ctx = Depends(require("devices:write"))):
    d = get_owned(ctx, Device, device_id, "device")
    if not ctx.principal.can_on_device("devices:write", d):
        raise HTTPException(403, "not allowed on this device")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device.delete",
        actor=ctx.user,
        target_type="device",
        target_id=d.id,
        target_name=d.hostname,
        before=model_snapshot(d, DEVICE_FIELDS),
        source_ip=ctx.ip,
    )
    ctx.db.delete(d)
    ctx.db.commit()


# --- device groups ---------------------------------------------------------------------


class DeviceGroupIn(BaseModel):
    name: str
    kind: str = "custom"  # region|pop|customer-edge|route-servers|core-routers|firewalls|custom
    description: str | None = None
    parent_id: uuid.UUID | None = None
    dynamic_filter: dict | None = None
    device_ids: list[uuid.UUID] = []


class DeviceGroupOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    parent_id: uuid.UUID | None
    dynamic_filter: dict | None
    device_count: int = 0


def apply_dynamic_membership(ctx: Ctx, g: DeviceGroup) -> None:
    f = g.dynamic_filter or {}
    if not f:
        return
    stmt = select(Device).where(Device.tenant_id == ctx.tenant_id)
    if "role" in f:
        stmt = stmt.where(Device.role == f["role"])
    if "platform" in f:
        stmt = stmt.where(Device.platform.has(Platform.slug == f["platform"]))
    if "site" in f:
        stmt = stmt.where(Device.site.has(Site.slug == f["site"]))
    if "hostname_regex" in f:
        stmt = stmt.where(Device.hostname.regexp_match(f["hostname_regex"]))
    g.devices = list(ctx.db.scalars(stmt))


def _group_out(g: DeviceGroup) -> DeviceGroupOut:
    o = DeviceGroupOut.model_validate(g)
    o.device_count = len(g.devices)
    return o


@router.get("/device-groups", response_model=list[DeviceGroupOut])
def list_device_groups(ctx: Ctx = Depends(require("devices:read"))):
    return [
        _group_out(g)
        for g in ctx.db.scalars(
            select(DeviceGroup)
            .where(DeviceGroup.tenant_id == ctx.tenant_id)
            .options(selectinload(DeviceGroup.devices))
            .order_by(DeviceGroup.name)
        )
    ]


@router.post("/device-groups", response_model=DeviceGroupOut, status_code=201)
def create_device_group(body: DeviceGroupIn, ctx: Ctx = Depends(require("devices:write"))):
    g = DeviceGroup(tenant_id=ctx.tenant_id, **body.model_dump(exclude={"device_ids"}))
    g.devices = list(
        ctx.db.scalars(select(Device).where(Device.tenant_id == ctx.tenant_id, Device.id.in_(body.device_ids)))
    )
    apply_dynamic_membership(ctx, g)
    ctx.db.add(g)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device_group.create",
        actor=ctx.user,
        target_type="device_group",
        target_id=g.id,
        target_name=g.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return _group_out(g)


@router.put("/device-groups/{group_id}", response_model=DeviceGroupOut)
def update_device_group(group_id: uuid.UUID, body: DeviceGroupIn, ctx: Ctx = Depends(require("devices:write"))):
    g = get_owned(ctx, DeviceGroup, group_id, "device group")
    for k, v in body.model_dump(exclude={"device_ids"}).items():
        setattr(g, k, v)
    g.devices = list(
        ctx.db.scalars(select(Device).where(Device.tenant_id == ctx.tenant_id, Device.id.in_(body.device_ids)))
    )
    apply_dynamic_membership(ctx, g)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device_group.update",
        actor=ctx.user,
        target_type="device_group",
        target_id=g.id,
        target_name=g.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return _group_out(g)


@router.delete("/device-groups/{group_id}", status_code=204)
def delete_device_group(group_id: uuid.UUID, ctx: Ctx = Depends(require("devices:write"))):
    g = get_owned(ctx, DeviceGroup, group_id, "device group")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="device_group.delete",
        actor=ctx.user,
        target_type="device_group",
        target_id=g.id,
        target_name=g.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(g)
    ctx.db.commit()


# --- topology --------------------------------------------------------------------------


@router.get("/topology")
def topology(site_id: uuid.UUID | None = None, ctx: Ctx = Depends(require("devices:read"))):
    """Graph for the network map: sites as clusters, devices as nodes, links as edges."""
    stmt = visible_devices_filter(ctx, _device_query(ctx))
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    devices = list(ctx.db.scalars(stmt))
    ids = {d.id for d in devices}
    links = ctx.db.scalars(
        select(Link).where(Link.tenant_id == ctx.tenant_id, Link.a_device_id.in_(ids), Link.b_device_id.in_(ids))
    )
    sites = {d.site.id: d.site for d in devices if d.site}
    return {
        "sites": [
            {"id": str(s.id), "name": s.name, "kind": s.kind, "lat": s.latitude, "lon": s.longitude}
            for s in sites.values()
        ],
        "nodes": [
            {
                "id": str(d.id),
                "label": d.hostname,
                "site_id": str(d.site_id) if d.site_id else None,
                "role": d.role,
                "platform": d.platform.slug if d.platform else None,
                "status": d.reachability,
                "backup": d.last_backup_status,
            }
            for d in devices
        ],
        "edges": [
            {
                "id": str(link.id),
                "source": str(link.a_device_id),
                "target": str(link.b_device_id),
                "label": f"{link.a_interface} - {link.b_interface}",
                "speed_mbps": link.speed_mbps,
                "status": link.status,
            }
            for link in links
        ],
    }
