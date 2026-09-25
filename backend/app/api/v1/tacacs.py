"""Module 2 - TACACS+ management API + tac_plus-ng agent endpoints."""

from __future__ import annotations

import re
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
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action=action,
        actor=ctx.user,
        target_type=obj.__tablename__,
        target_id=obj.id,
        target_name=name,
        source_ip=ctx.ip,
        **kw,
    )


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
    running_sha256: str | None = None
    agent_status: str | None = None
    agent_message: str | None = None


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
    return ctx.db.scalars(
        select(TacacsDevice).where(TacacsDevice.tenant_id == ctx.tenant_id).order_by(TacacsDevice.name)
    ).all()


@router.post("/devices", response_model=NasOut, status_code=201)
def create_nas(body: NasIn, ctx: Ctx = Depends(require("tacacs:write"))):
    if body.device_id:
        get_owned(ctx, Device, body.device_id, "device")
    if body.device_group_id:
        get_owned(ctx, DeviceGroup, body.device_group_id, "device group")
    key = body.key or secrets.token_urlsafe(24)
    n = TacacsDevice(
        tenant_id=ctx.tenant_id,
        key_enc=encrypt_secret(key),
        key_rotated_at=utcnow(),
        **body.model_dump(exclude={"key"}),
    )
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
        if not d.management_ip:
            continue  # no address (e.g. synced from NetBox without a primary IP)
        if d.id in have:
            continue
        vendor = d.vendor.slug if d.vendor and d.vendor.slug in VENDORS else "generic"
        n = TacacsDevice(
            tenant_id=ctx.tenant_id,
            name=d.hostname,
            address=d.management_ip,
            device_id=d.id,
            vendor=vendor,
            key_enc=encrypt_secret(secrets.token_urlsafe(24)),
            key_rotated_at=utcnow(),
        )
        ctx.db.add(n)
        created.append(n)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="tacacs.device.import",
        actor=ctx.user,
        after={"created": len(created)},
        source_ip=ctx.ip,
    )
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


# tac_plus-ng ``time`` objects: crontab(5) style "min hour day month weekday" (no */step) or
# Taylor-UUCP items such as "Wk0800-1800", "Sa,Su", "Any" (doc/tac_plus-ng "Time Ranges").
_CRON_FIELD = r"(?:\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)(?:,(?:\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?))*"
_CRON = re.compile(rf"^{_CRON_FIELD}(?: {_CRON_FIELD}){{4}}$")
_UUCP_ITEM = r"(?:Any|Wk|Su|Mo|Tu|We|Th|Fr|Sa)(?:\d{4}-\d{4})?"
_UUCP = re.compile(rf"^{_UUCP_ITEM}(?:,{_UUCP_ITEM})*$")


def validate_time_window(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = " ".join(v.split())
    if not (_CRON.match(v) or _UUCP.match(v)):
        raise ValueError(
            "time_window must be a cron spec like '* 8-17 * * 1-5' or UUCP ranges like 'Wk0800-1800' / 'Sa,Su'"
        )
    return v


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

    @field_validator("time_window")
    @classmethod
    def _time_window(cls, v: str | None) -> str | None:
        return validate_time_window(v)


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
    return ctx.db.scalars(
        select(TacacsPolicy)
        .where(TacacsPolicy.tenant_id == ctx.tenant_id)
        .options(selectinload(TacacsPolicy.command_rules))
        .order_by(TacacsPolicy.priority)
    ).all()


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
    return [
        _mapping_out(m)
        for m in ctx.db.scalars(select(TacacsUserMapping).where(TacacsUserMapping.tenant_id == ctx.tenant_id))
    ]


@router.post("/users", response_model=MappingOut, status_code=201)
def create_mapping(body: MappingIn, ctx: Ctx = Depends(require("tacacs:write"))):
    from app.core.security import PasswordPolicyError, validate_password_policy

    u = get_owned(ctx, User, body.user_id, "user")
    if body.auth_method not in ("crypt", "ldap"):
        raise HTTPException(422, "auth_method must be crypt or ldap")
    m = TacacsUserMapping(
        tenant_id=ctx.tenant_id,
        user_id=u.id,
        tacacs_username=body.tacacs_username or u.username,
        auth_method=body.auth_method,
        enabled=body.enabled,
        valid_until=body.valid_until,
    )
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


class MappingPatch(BaseModel):
    tacacs_username: str | None = None
    auth_method: str | None = None
    password: str | None = None
    clear_password: bool = False
    enabled: bool | None = None
    valid_until: datetime | None = None


@router.patch("/users/{mapping_id}", response_model=MappingOut)
def update_mapping(mapping_id: uuid.UUID, body: MappingPatch, ctx: Ctx = Depends(require("tacacs:write"))):
    """Enable/disable, set expiry (``valid_until: null`` clears it), change auth method or set a new
    device password (checked against the password policy; stored as crypt(3) only)."""
    from app.core.security import PasswordPolicyError, validate_password_policy

    m = get_owned(ctx, TacacsUserMapping, mapping_id, "mapping")
    data = body.model_dump(exclude_unset=True, exclude={"password", "clear_password"})
    if data.get("auth_method") is not None and data["auth_method"] not in ("crypt", "ldap"):
        raise HTTPException(422, "auth_method must be crypt or ldap")
    if "tacacs_username" in data and not data["tacacs_username"]:
        raise HTTPException(422, "tacacs_username cannot be empty")
    for k in ("auth_method", "enabled"):
        if k in data and data[k] is None:
            raise HTTPException(422, f"{k} cannot be null")
    before = {**_mapping_out(m).model_dump(mode="json", exclude={"id", "user_id"})}
    for k, v in data.items():
        setattr(m, k, v)
    if body.password:
        owner = ctx.db.get(User, m.user_id)
        try:
            validate_password_policy(body.password, owner.username if owner else m.tacacs_username)
        except PasswordPolicyError as e:
            raise HTTPException(422, str(e)) from e
        m.password_crypt = tacacs_crypt(body.password)
    elif body.clear_password:
        m.password_crypt = None
    after = _mapping_out(m).model_dump(mode="json", exclude={"id", "user_id"})
    if body.password:
        after["password_changed"] = True
    _audit(ctx, "tacacs.user.update", m, m.tacacs_username, before=before, after=after)
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


def _deploy(ctx: Ctx, s: TacacsServer) -> tuple[TacacsConfigRevision, bool, list[str]]:
    """Publish a revision for one server; returns (revision, created, warnings). No-op when unchanged."""
    r = render_for_tenant(ctx.db, ctx.tenant_id, s)
    if r.sha256 == s.config_sha256:
        rev = ctx.db.scalar(
            select(TacacsConfigRevision)
            .where(TacacsConfigRevision.server_id == s.id)
            .order_by(TacacsConfigRevision.version.desc())
            .limit(1)
        )
        if rev:
            return rev, False, r.warnings
    s.config_version += 1
    s.config_sha256 = r.sha256
    s.last_deployed_at = utcnow()
    rev = TacacsConfigRevision(
        tenant_id=ctx.tenant_id,
        server_id=s.id,
        version=s.config_version,
        sha256=r.sha256,
        content=redact_keys(r.content),
        generated_by=ctx.user.id,
    )
    ctx.db.add(rev)
    ctx.db.flush()
    _audit(
        ctx, "tacacs.deploy", s, s.name, after={"version": s.config_version, "sha256": r.sha256, "warnings": r.warnings}
    )
    return rev, True, r.warnings


@router.post("/servers/{server_id}/deploy", response_model=RevisionOut)
def deploy(server_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:deploy"))):
    """Publish a new config revision. The agent on the TACACS host pulls it, validates with
    ``tac_plus-ng -P`` and reloads; it reports back via heartbeat."""
    s = get_owned(ctx, TacacsServer, server_id, "server")
    rev, _, _ = _deploy(ctx, s)
    ctx.db.commit()
    return rev


class DeployAllItem(BaseModel):
    server_id: uuid.UUID
    name: str
    version: int
    sha256: str
    created: bool  # False: the server already had this configuration


class DeployAllOut(BaseModel):
    deployed: list[DeployAllItem]
    skipped: list[str]  # disabled servers
    warnings: list[str]


@router.post("/servers/deploy-all", response_model=DeployAllOut)
def deploy_all(ctx: Ctx = Depends(require("tacacs:deploy"))):
    """Publish the current configuration to every enabled server in one step. Each agent pulls,
    validates and reloads independently; progress shows in ``GET /tacacs/servers``
    (``running_sha256`` == ``config_sha256`` once applied)."""
    out = DeployAllOut(deployed=[], skipped=[], warnings=[])
    for s in ctx.db.scalars(
        select(TacacsServer).where(TacacsServer.tenant_id == ctx.tenant_id).order_by(TacacsServer.name)
    ):
        if not s.enabled:
            out.skipped.append(s.name)
            continue
        rev, created, warnings = _deploy(ctx, s)
        out.deployed.append(DeployAllItem(server_id=s.id, name=s.name, version=rev.version, sha256=rev.sha256, created=created))
        out.warnings.extend(w for w in warnings if w not in out.warnings)
    ctx.db.commit()
    return out


@router.get("/servers/{server_id}/revisions", response_model=list[RevisionOut])
def revisions(server_id: uuid.UUID, ctx: Ctx = Depends(require("tacacs:read"))):
    get_owned(ctx, TacacsServer, server_id, "server")
    return ctx.db.scalars(
        select(TacacsConfigRevision)
        .where(TacacsConfigRevision.server_id == server_id)
        .order_by(TacacsConfigRevision.version.desc())
        .limit(100)
    ).all()


# --- agent (runs next to tac_plus-ng) ---------------------------------------------------------


def _agent_server(db: Session, authorization: str | None) -> TacacsServer:
    token = (authorization or "").removeprefix("Bearer ").strip()
    s = db.scalar(select(TacacsServer).where(TacacsServer.agent_token_hash == sha256(token))) if token else None
    if s is None or not s.enabled:
        raise HTTPException(401, "invalid agent token")
    return s


@router.get("/agent/config", response_class=PlainTextResponse, include_in_schema=True)
def agent_config(
    authorization: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    s = _agent_server(db, authorization)
    r = render_for_tenant(db, s.tenant_id, s)
    if s.config_sha256 is None:
        raise HTTPException(404, "no configuration deployed yet")
    if r.sha256 != s.config_sha256:
        # Only hand out what an operator explicitly deployed.
        raise HTTPException(409, "rendered configuration differs from the deployed revision; redeploy")
    if if_none_match and s.config_sha256 in if_none_match.lower():  # tolerate quotes, W/, -gzip suffixes
        return PlainTextResponse("", status_code=304)
    return PlainTextResponse(
        r.content,
        headers={
            "ETag": f'"{s.config_sha256}"',
            # proxies may rewrite ETag (Caddy's encode appends -gzip); agents verify against this header
            "X-Config-Sha256": s.config_sha256,
            "X-Config-Version": str(s.config_version),
            "Cache-Control": "no-store, no-transform",
        },
    )


class HeartbeatIn(BaseModel):
    running_sha256: str | None = None
    status: str = "ok"
    message: str | None = None


@router.post("/agent/heartbeat", status_code=204)
def agent_heartbeat(body: HeartbeatIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    s = _agent_server(db, authorization)
    s.last_heartbeat_at = utcnow()
    s.running_sha256 = body.running_sha256
    s.agent_status = (body.status or "")[:16]
    s.agent_message = body.message
    if body.status != "ok":
        from app.services.alerting import emit_event

        emit_event(
            db,
            s.tenant_id,
            "tacacs_deploy_failed",
            severity="critical",
            title=f"tac_plus-ng on {s.name} rejected configuration",
            body=body.message,
            dedup_key=f"tacdeploy:{s.id}:{body.running_sha256}",
        )
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
def auth_events(
    username: str | None = None,
    result: str | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("accounting:read")),
):
    stmt = (
        select(TacacsAuthEvent)
        .where(TacacsAuthEvent.tenant_id == ctx.tenant_id)
        .order_by(TacacsAuthEvent.timestamp.desc())
    )
    if username:
        stmt = stmt.where(TacacsAuthEvent.username == username)
    if result:
        stmt = stmt.where(TacacsAuthEvent.result == result)
    return paginate(ctx.db, stmt, AuthEventOut, limit, offset)


# --- import an existing Shrubbery tac_plus configuration ----------------------------------------


class ImportIn(BaseModel):
    content: str
    dry_run: bool = True


class ImportOut(BaseModel):
    dry_run: bool
    created: dict[str, list[str]]
    skipped: dict[str, list[str]]
    warnings: list[str]
    users_needing_password: list[str]
    conflicts: list[str] = []  # same object, different definition: portal's version kept
    updated: list[str] = []  # changes applied to existing objects
    rendered: str  # resulting tac_plus-ng config, keys redacted


@router.post("/import", response_model=ImportOut)
def import_tac_plus(body: ImportIn, ctx: Ctx = Depends(require("tacacs:write"))):
    """Import a classic Shrubbery ``tac_plus`` (F4.0.4.x) config: NAS clients with their existing keys,
    groups, users with their existing password hashes, and command authorization as policies.
    ``dry_run`` (default) shows what would be created plus the resulting tac_plus-ng config, and
    changes nothing."""
    from app.services.tacacs.importer import import_config
    from app.services.tacacs.shrubbery import ParseError

    if len(body.content) > 5_000_000:
        raise HTTPException(413, "configuration too large")
    try:
        res = import_config(ctx.db, ctx.tenant_id, body.content)
    except ParseError as e:
        ctx.db.rollback()
        raise HTTPException(422, f"could not parse tac_plus config: {e}") from e
    rendered = redact_keys(render_for_tenant(ctx.db, ctx.tenant_id).content)
    out = ImportOut(
        dry_run=body.dry_run,
        created=res.created,
        skipped=res.skipped,
        warnings=res.warnings,
        users_needing_password=res.users_needing_password,
        conflicts=res.conflicts,
        updated=res.updated,
        rendered=rendered,
    )
    if body.dry_run:
        ctx.db.rollback()
        return out
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="tacacs.import",
        actor=ctx.user,
        target_type="tacacs",
        after={k: len(v) for k, v in res.created.items()},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return out
