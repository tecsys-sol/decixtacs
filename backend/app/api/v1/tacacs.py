"""Module 2 - TACACS+ management API + tac_plus-ng agent endpoints."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Ctx, get_owned, require
from app.api.v1.common import ORM, Page, paginate
from app.core.security import encrypt_secret, sha256
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    Device,
    DeviceGroup,
    Group,
    TacacsAuthEvent,
    TacacsCommandPolicy,
    TacacsConfigRevision,
    TacacsDevice,
    TacacsPolicy,
    TacacsServer,
    TacacsUserMapping,
    User,
)
from app.services import audit
from app.services.tacacs.builder import render_for_tenant
from app.services.tacacs.crypt import tacacs_crypt
from app.services.tacacs.generator import redact_keys

router = APIRouter(prefix="/tacacs", tags=["tacacs"])

VENDORS = {"juniper", "cisco", "arista", "fortinet", "sophos", "mikrotik", "generic"}


def _audit(ctx: Ctx, action: str, obj, name: str, **kw):
    audit.record(ctx.db, tenant_id=ctx.tenant_id, action=action, actor=ctx.user, target_type=obj.__tablename__,
                 target_id=obj.id, target_name=name, source_ip=ctx.ip, **kw)


# --- servers ------------------------------------------------------------------------


class ServerIn(BaseModel):
    name: str
    address: str
    port: int = 49
    enabled: bool = True
    ldap_backend: bool = False


class ServerOut(ServerIn, ORM):
    id: uuid.UUID
    config_version: int
    config_sha256: str | None
    last_deployed_at: datetime | None
    last_heartbeat_at: datetime | None


class ServerCreated(ServerOut):
    agent_token: str


@router.get("/servers", response_model=list[ServerOut])
def list_servers(ctx: Ctx = Depends(require("tacacs:read"))):
    return ctx.db.scalars(select(TacacsServer).where(TacacsServer.tenant_id == ctx.tenant_id)).all()


@router.post("/servers", response_model=ServerCreated, status_code=201)
def create_server(body: ServerIn, ctx: Ctx = Depends(require("tacacs:write"))):
    token = f"nomagent_{secrets.token_urlsafe(32)}"
    s = TacacsServer(tenant_id=ctx.tenant_id, agent_token_hash=sha256(token), **body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    _audit(ctx, "tacacs.server.create", s, s.name, after=body.model_dump())
    ctx.db.commit()
    return ServerCreated.model_validate({**ServerOut.model_validate(s).model_dump(), "agent_token": token})


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:write"))):
    s = get_owned(ctx, TacacsServer, server_id, "server")
    _audit(ctx, "tacacs.server.delete", s, s.name)
    ctx.db.delete(s)
    ctx.db.commit()


# --- NAS clients --------------------------------------------------------------------


class NasIn(BaseModel):
    name: str
    address: str
    key: str | None = None  # generated when omitted
    vendor: str
    device_id: uuid.UUID | None = None
    device_group_id: uuid.UUID | None = None
    enabled: bool = True

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, v: str) -> str:
        if v not in VENDORS:
            raise ValueError(f"vendor must be one of {sorted(VENDORS)}")
        return v


class NasOut(ORM):
    id: uuid.UUID
    name: str
    address: str
    vendor: str
    device_id: uuid.UUID | None
    device_group_id: uuid.UUID | None
    enabled: bool
    key_rotated_at: datetime | None


@router.get("/devices", response_model=list[NasOut])
def list_nas(ctx: Ctx = Depends(require("tacacs:read"))):
    return ctx.db.scalars(select(TacacsDevice).where(TacacsDevice.tenant_id == ctx.tenant_id).order_by(TacacsDevice.name)).all()


@router.post("/devices", response_model=NasOut, status_code=201)
def create_nas(body: NasIn, ctx: Ctx = Depends(require("tacacs:write"))):
    if body.device_id:
        get_owned(ctx, Device, body.device_id, "device")
    if body.device_group_id:
        get_owned(ctx, DeviceGroup, body.device_group_id, "device group")
    key = body.key or secrets.token_urlsafe(24)
    n = TacacsDevice(tenant_id=ctx.tenant_id, key_enc=encrypt_secret(key), key_rotated_at=utcnow(),
                     **body.model_dump(exclude={"key"}))
    ctx.db.add(n)
    ctx.db.flush()
    _audit(ctx, "tacacs.device.create", n, n.name, after=body.model_dump(mode="json", exclude={"key"}))
    ctx.db.commit()
    return n


@router.post("/devices/import-inventory", response_model=list[NasOut])
def import_from_inventory(device_group_id: uuid.UUID | None = None, ctx: Ctx = Depends(require("tacacs:write"))):
    """Create NAS entries for inventory devices that do not have one yet (one random key per device)."""
    stmt = select(Device).where(Device.tenant_id == ctx.tenant_id).options(selectinload(Device.vendor))
    if device_group_id:
        stmt = stmt.where(Device.groups.any(DeviceGroup.id == device_group_id))
    have = set(ctx.db.scalars(select(TacacsDevice.device_id).where(TacacsDevice.tenant_id == ctx.tenant_id)))
    created = []
    for d in ctx.db.scalars(stmt):
        if d.id in have:
            continue
        vendor = d.vendor.slug if d.vendor and d.vendor.slug in VENDORS else "generic"
        n = TacacsDevice(tenant_id=ctx.tenant_id, name=d.hostname, address=d.management_ip, device_id=d.id,
                         vendor=vendor, key_enc=encrypt_secret(secrets.token_urlsafe(24)), key_rotated_at=utcnow())
        ctx.db.add(n)
        created.append(n)
    ctx.db.flush()
    audit.record(ctx.db, tenant_id=ctx.tenant_id, action="tacacs.device.import", actor=ctx.user,
                 after={"created": len(created)}, source_ip=ctx.ip)
    ctx.db.commit()
    return created


@router.post("/devices/{nas_id}/rotate-key")
def rotate_nas_key(nas_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:write"))):
    """Rotate the shared secret. The new key is returned once so it can be configured on the device."""
    n = get_owned(ctx, TacacsDevice, nas_id, "NAS")
    key = secrets.token_urlsafe(24)
    n.key_enc, n.key_rotated_at = encrypt_secret(key), utcnow()
    _audit(ctx, "tacacs.device.rotate_key", n, n.name)
    ctx.db.commit()
    return {"key": key}


@router.delete("/devices/{nas_id}", status_code=204)
def delete_nas(nas_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:write"))):
    n = get_owned(ctx, TacacsDevice, nas_id, "NAS")
    _audit(ctx, "tacacs.device.delete", n, n.name)
    ctx.db.delete(n)
    ctx.db.commit()


# --- policies -------------------------------------------------------------------------


class CommandRuleIn(BaseModel):
    sequence: int = 10
    action: str
    pattern: str
    description: str | None = None
    alert_on_match: bool = False

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in ("permit", "deny"):
            raise ValueError("action must be permit or deny")
        return v

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, v: str) -> str:
        import re

        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e
        return v


class CommandRuleOut(CommandRuleIn, ORM):
    id: uuid.UUID


class PolicyIn(BaseModel):
    name: str
    description: str | None = None
    priority: int = 100
    group_id: uuid.UUID
    device_group_id: uuid.UUID | None = None
    privilege_level: int = 1
    junos_class: str | None = None
    fortigate_profile: str | None = None
    arista_role: str | None = None
    extra_attributes: dict = {}
    default_action: str = "deny"
    time_window: str | None = None
    enabled: bool = True
    command_rules: list[CommandRuleIn] = []


class PolicyOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    group_id: uuid.UUID
    device_group_id: uuid.UUID | None
    privilege_level: int
    junos_class: str | None
    fortigate_profile: str | None
    arista_role: str | None
    extra_attributes: dict
    default_action: str
    time_window: str | None
    enabled: bool
    command_rules: list[CommandRuleOut]
    updated_at: datetime


def _apply_policy(ctx: Ctx, p: TacacsPolicy, body: PolicyIn) -> None:
    get_owned(ctx, Group, body.group_id, "group")
    if body.device_group_id:
        get_owned(ctx, DeviceGroup, body.device_group_id, "device group")
    if not 0 <= body.privilege_level <= 15:
        raise HTTPException(422, "privilege_level must be 0-15")
    for k, v in body.model_dump(exclude={"command_rules"}).items():
        setattr(p, k, v)
    p.command_rules = [TacacsCommandPolicy(tenant_id=ctx.tenant_id, **r.model_dump()) for r in body.command_rules]


@router.get("/policies", response_model=list[PolicyOut])
def list_policies(ctx: Ctx = Depends(require("tacacs:read"))):
    return ctx.db.scalars(select(TacacsPolicy).where(TacacsPolicy.tenant_id == ctx.tenant_id)
                          .options(selectinload(TacacsPolicy.command_rules)).order_by(TacacsPolicy.priority)).all()


@router.post("/policies", response_model=PolicyOut, status_code=201)
def create_policy(body: PolicyIn, ctx: Ctx = Depends(require("tacacs:write"))):
    p = TacacsPolicy(tenant_id=ctx.tenant_id)
    _apply_policy(ctx, p, body)
    ctx.db.add(p)
    ctx.db.flush()
    _audit(ctx, "tacacs.policy.create", p, p.name, after=body.model_dump(mode="json"))
    ctx.db.commit()
    return p


@router.put("/policies/{policy_id}", response_model=PolicyOut)
def update_policy(policy_id: uuid.UUID, body: PolicyIn, ctx: Ctx = Depends(require("tacacs:write"))):
    p = get_owned(ctx, TacacsPolicy, policy_id, "policy")
    before = PolicyOut.model_validate(p).model_dump(mode="json")
    _apply_policy(ctx, p, body)
    _audit(ctx, "tacacs.policy.update", p, p.name, before=before, after=body.model_dump(mode="json"))
    ctx.db.commit()
    return p


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:write"))):
    p = get_owned(ctx, TacacsPolicy, policy_id, "policy")
    _audit(ctx, "tacacs.policy.delete", p, p.name)
    ctx.db.delete(p)
    ctx.db.commit()


# --- user mappings ----------------------------------------------------------------------


class MappingIn(BaseModel):
    user_id: uuid.UUID
    tacacs_username: str | None = None
    auth_method: str = "crypt"
    password: str | None = None
    enabled: bool = True
    valid_until: datetime | None = None


class MappingOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    tacacs_username: str
    auth_method: str
    enabled: bool
    valid_until: datetime | None
    has_password: bool = False


def _mapping_out(m: TacacsUserMapping) -> MappingOut:
    o = MappingOut.model_validate(m)
    o.has_password = bool(m.password_crypt)
    return o


@router.get("/users", response_model=list[MappingOut])
def list_mappings(ctx: Ctx = Depends(require("tacacs:read"))):
    return [_mapping_out(m) for m in ctx.db.scalars(select(TacacsUserMapping).where(TacacsUserMapping.tenant_id == ctx.tenant_id))]


@router.post("/users", response_model=MappingOut, status_code=201)
def create_mapping(body: MappingIn, ctx: Ctx = Depends(require("tacacs:write"))):
    from app.core.security import PasswordPolicyError, validate_password_policy

    u = get_owned(ctx, User, body.user_id, "user")
    if body.auth_method not in ("crypt", "ldap"):
        raise HTTPException(422, "auth_method must be crypt or ldap")
    m = TacacsUserMapping(tenant_id=ctx.tenant_id, user_id=u.id, tacacs_username=body.tacacs_username or u.username,
                          auth_method=body.auth_method, enabled=body.enabled, valid_until=body.valid_until)
    if body.password:
        try:
            validate_password_policy(body.password, u.username)
        except PasswordPolicyError as e:
            raise HTTPException(422, str(e)) from e
        m.password_crypt = tacacs_crypt(body.password)
    ctx.db.add(m)
    ctx.db.flush()
    _audit(ctx, "tacacs.user.create", m, m.tacacs_username, after=body.model_dump(mode="json", exclude={"password"}))
    ctx.db.commit()
    return _mapping_out(m)


@router.delete("/users/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:write"))):
    m = get_owned(ctx, TacacsUserMapping, mapping_id, "mapping")
    _audit(ctx, "tacacs.user.delete", m, m.tacacs_username)
    ctx.db.delete(m)
    ctx.db.commit()


# --- render & deploy ----------------------------------------------------------------------


class RenderOut(BaseModel):
    sha256: str
    warnings: list[str]
    content: str  # keys redacted


class RevisionOut(ORM):
    id: uuid.UUID
    server_id: uuid.UUID
    version: int
    sha256: str
    created_at: datetime


@router.get("/render", response_model=RenderOut)
def render_preview(server_id: uuid.UUID | None = None, ctx: Ctx = Depends(require("tacacs:read"))):
    server = get_owned(ctx, TacacsServer, server_id, "server") if server_id else None
    r = render_for_tenant(ctx.db, ctx.tenant_id, server)
    return RenderOut(sha256=r.sha256, warnings=r.warnings, content=redact_keys(r.content))


@router.post("/servers/{server_id}/deploy", response_model=RevisionOut)
def deploy(server_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:deploy"))):
    """Publish a new config revision. The agent on the TACACS host pulls it, validates with
    ``tac_plus-ng -P`` and reloads; it reports back via heartbeat."""
    s = get_owned(ctx, TacacsServer, server_id, "server")
    r = render_for_tenant(ctx.db, ctx.tenant_id, s)
    if r.sha256 == s.config_sha256:
        rev = ctx.db.scalar(select(TacacsConfigRevision).where(TacacsConfigRevision.server_id == s.id)
                            .order_by(TacacsConfigRevision.version.desc()).limit(1))
        if rev:
            return rev
    s.config_version += 1
    s.config_sha256 = r.sha256
    s.last_deployed_at = utcnow()
    rev = TacacsConfigRevision(tenant_id=ctx.tenant_id, server_id=s.id, version=s.config_version, sha256=r.sha256,
                               content=redact_keys(r.content), generated_by=ctx.user.id)
    ctx.db.add(rev)
    ctx.db.flush()
    _audit(ctx, "tacacs.deploy", s, s.name, after={"version": s.config_version, "sha256": r.sha256,
                                                    "warnings": r.warnings})
    ctx.db.commit()
    return rev


@router.get("/servers/{server_id}/revisions", response_model=list[RevisionOut])
def revisions(server_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:read"))):
    get_owned(ctx, TacacsServer, server_id, "server")
    return ctx.db.scalars(select(TacacsConfigRevision).where(TacacsConfigRevision.server_id == server_id)
                          .order_by(TacacsConfigRevision.version.desc()).limit(100)).all()


# --- agent (runs next to tac_plus-ng) ---------------------------------------------------------


def _agent_server(db: Session, authorization: str | None) -> TacacsServer:
    token = (authorization or "").removeprefix("Bearer ").strip()
    s = db.scalar(select(TacacsServer).where(TacacsServer.agent_token_hash == sha256(token))) if token else None
    if s is None or not s.enabled:
        raise HTTPException(401, "invalid agent token")
    return s


@router.get("/agent/config", response_class=PlainTextResponse, include_in_schema=True)
def agent_config(authorization: str | None = Header(default=None), if_none_match: str | None = Header(default=None),
                 db: Session = Depends(get_db)):
    s = _agent_server(db, authorization)
    r = render_for_tenant(db, s.tenant_id, s)
    if s.config_sha256 is None:
        raise HTTPException(404, "no configuration deployed yet")
    if r.sha256 != s.config_sha256:
        # Only hand out what an operator explicitly deployed.
        raise HTTPException(409, "rendered configuration differs from the deployed revision; redeploy")
    if if_none_match == s.config_sha256:
        return PlainTextResponse("", status_code=304)
    return PlainTextResponse(r.content, headers={"ETag": s.config_sha256, "X-Config-Version": str(s.config_version)})


class HeartbeatIn(BaseModel):
    running_sha256: str | None = None
    status: str = "ok"
    message: str | None = None


@router.post("/agent/heartbeat", status_code=204)
def agent_heartbeat(body: HeartbeatIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    s = _agent_server(db, authorization)
    s.last_heartbeat_at = utcnow()
    if body.status != "ok":
        from app.services.alerting import emit_event

        emit_event(db, s.tenant_id, "tacacs_deploy_failed", severity="critical",
                   title=f"tac_plus-ng on {s.name} rejected configuration", body=body.message,
                   dedup_key=f"tacdeploy:{s.id}:{body.running_sha256}")
    db.commit()


# --- auth events --------------------------------------------------------------------------


class AuthEventOut(ORM):
    id: uuid.UUID
    timestamp: datetime
    username: str
    device_address: str
    source_address: str | None
    kind: str
    result: str
    detail: str | None


@router.get("/events", response_model=Page[AuthEventOut])
def auth_events(username: str | None = None, result: str | None = None, limit: int = Query(100, le=1000),
                offset: int = 0, ctx: Ctx = Depends(require("accounting:read"))):
    stmt = select(TacacsAuthEvent).where(TacacsAuthEvent.tenant_id == ctx.tenant_id).order_by(TacacsAuthEvent.timestamp.desc())
    if username:
        stmt = stmt.where(TacacsAuthEvent.username == username)
    if result:
        stmt = stmt.where(TacacsAuthEvent.result == result)
    return paginate(ctx.db, stmt, AuthEventOut, limit, offset)
