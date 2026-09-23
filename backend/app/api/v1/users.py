"""Module 1 - users, groups, roles, role bindings (RBAC/ABAC), login history; Module 19 - tenants."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import Ctx, get_owned, require
from app.api.v1.auth import set_password
from app.api.v1.common import ORM, Page, paginate
from app.models import Group, LoginHistory, Permission, Role, RoleBinding, Tenant, User
from app.services import audit
from app.services.audit import model_snapshot

router = APIRouter(tags=["users"])

USER_FIELDS = ["username", "email", "full_name", "is_active", "is_superuser", "auth_source", "mfa_enabled"]


class UserIn(BaseModel):
    username: str
    email: EmailStr | None = None
    full_name: str | None = None
    password: str | None = None
    auth_source: str = "local"
    is_active: bool = True
    group_ids: list[uuid.UUID] = []


class UserPatch(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    password: str | None = None
    is_active: bool | None = None
    group_ids: list[uuid.UUID] | None = None
    reset_mfa: bool = False
    unlock: bool = False


class GroupRef(ORM):
    id: uuid.UUID
    name: str


class UserOut(ORM):
    id: uuid.UUID
    username: str
    email: str | None
    full_name: str | None
    auth_source: str
    is_active: bool
    is_superuser: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    created_at: datetime
    groups: list[GroupRef] = []


@router.get("/users", response_model=Page[UserOut])
def list_users(
    q: str | None = None, limit: int = Query(50, le=500), offset: int = 0, ctx: Ctx = Depends(require("users:read"))
):
    stmt = (
        select(User).where(User.tenant_id == ctx.tenant_id).options(selectinload(User.groups)).order_by(User.username)
    )
    if q:
        stmt = stmt.where(
            or_(User.username.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )
    return paginate(ctx.db, stmt, UserOut, limit, offset)


def _groups(ctx: Ctx, ids: list[uuid.UUID]) -> list[Group]:
    groups = list(ctx.db.scalars(select(Group).where(Group.tenant_id == ctx.tenant_id, Group.id.in_(ids))))
    if len(groups) != len(set(ids)):
        raise HTTPException(422, "unknown group id")
    return groups


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, ctx: Ctx = Depends(require("users:write"))):
    if ctx.db.scalar(select(User.id).where(User.tenant_id == ctx.tenant_id, User.username == body.username)):
        raise HTTPException(409, "username already exists")
    u = User(
        tenant_id=ctx.tenant_id,
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        auth_source=body.auth_source,
        is_active=body.is_active,
    )
    if body.auth_source == "local":
        if not body.password:
            raise HTTPException(422, "password required for local users")
        set_password(u, body.password)
    u.groups = _groups(ctx, body.group_ids)
    ctx.db.add(u)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="user.create",
        actor=ctx.user,
        target_type="user",
        target_id=u.id,
        target_name=u.username,
        after=model_snapshot(u, USER_FIELDS),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return u


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, ctx: Ctx = Depends(require("users:read"))):
    return get_owned(ctx, User, user_id, "user")


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserPatch, ctx: Ctx = Depends(require("users:write"))):
    u = get_owned(ctx, User, user_id, "user")
    before = model_snapshot(u, USER_FIELDS) | {"groups": sorted(g.name for g in u.groups)}
    for f in ("email", "full_name", "is_active"):
        if (v := getattr(body, f)) is not None:
            setattr(u, f, v)
    if body.password:
        set_password(u, body.password)
    if body.group_ids is not None:
        u.groups = _groups(ctx, body.group_ids)
    if body.reset_mfa:
        u.mfa_enabled, u.mfa_secret_enc = False, None
    if body.unlock:
        u.failed_logins, u.locked_until = 0, None
    after = model_snapshot(u, USER_FIELDS) | {"groups": sorted(g.name for g in u.groups)}
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="user.update",
        actor=ctx.user,
        target_type="user",
        target_id=u.id,
        target_name=u.username,
        before=before,
        after=after,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return u


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: uuid.UUID, ctx: Ctx = Depends(require("users:write"))):
    u = get_owned(ctx, User, user_id, "user")
    if u.id == ctx.user.id:
        raise HTTPException(400, "you cannot delete yourself")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="user.delete",
        actor=ctx.user,
        target_type="user",
        target_id=u.id,
        target_name=u.username,
        before=model_snapshot(u, USER_FIELDS),
        source_ip=ctx.ip,
    )
    ctx.db.delete(u)
    ctx.db.commit()


# --- groups --------------------------------------------------------------------


class GroupIn(BaseModel):
    name: str
    description: str | None = None
    source: str = "local"
    external_dn: str | None = None


class GroupOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    source: str
    external_dn: str | None
    created_at: datetime


@router.get("/groups", response_model=list[GroupOut])
def list_groups(ctx: Ctx = Depends(require("users:read"))):
    return ctx.db.scalars(select(Group).where(Group.tenant_id == ctx.tenant_id).order_by(Group.name)).all()


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(body: GroupIn, ctx: Ctx = Depends(require("users:write"))):
    g = Group(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(g)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="group.create",
        actor=ctx.user,
        target_type="group",
        target_id=g.id,
        target_name=g.name,
        after=body.model_dump(),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return g


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(group_id: uuid.UUID, body: GroupIn, ctx: Ctx = Depends(require("users:write"))):
    g = get_owned(ctx, Group, group_id, "group")
    before = model_snapshot(g, list(GroupIn.model_fields))
    for k, v in body.model_dump().items():
        setattr(g, k, v)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="group.update",
        actor=ctx.user,
        target_type="group",
        target_id=g.id,
        target_name=g.name,
        before=before,
        after=body.model_dump(),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return g


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: uuid.UUID, ctx: Ctx = Depends(require("users:write"))):
    g = get_owned(ctx, Group, group_id, "group")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="group.delete",
        actor=ctx.user,
        target_type="group",
        target_id=g.id,
        target_name=g.name,
        source_ip=ctx.ip,
    )
    ctx.db.delete(g)
    ctx.db.commit()


# --- roles & bindings ------------------------------------------------------------


class PermissionOut(ORM):
    code: str
    description: str | None


class RoleIn(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


class RoleOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    builtin: bool
    permissions: list[PermissionOut]


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(ctx: Ctx = Depends(require("users:read"))):
    return ctx.db.scalars(select(Permission).order_by(Permission.code)).all()


@router.get("/roles", response_model=list[RoleOut])
def list_roles(ctx: Ctx = Depends(require("users:read"))):
    return ctx.db.scalars(
        select(Role)
        .where(or_(Role.tenant_id.is_(None), Role.tenant_id == ctx.tenant_id))
        .options(selectinload(Role.permissions))
        .order_by(Role.name)
    ).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(body: RoleIn, ctx: Ctx = Depends(require("users:write"))):
    perms = list(ctx.db.scalars(select(Permission).where(Permission.code.in_(body.permissions))))
    if len(perms) != len(set(body.permissions)):
        raise HTTPException(422, "unknown permission code")
    if not ctx.user.is_superuser and not {p.code for p in perms} <= ctx.principal.permissions:
        raise HTTPException(403, "cannot create a role with permissions you do not hold")
    r = Role(tenant_id=ctx.tenant_id, name=body.name, description=body.description, permissions=perms)
    ctx.db.add(r)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="role.create",
        actor=ctx.user,
        target_type="role",
        target_id=r.id,
        target_name=r.name,
        after=body.model_dump(),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return r


class BindingIn(BaseModel):
    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    scope_type: str | None = None  # site | device_group
    scope_id: uuid.UUID | None = None
    conditions: dict = {}


class BindingOut(ORM):
    id: uuid.UUID
    role_id: uuid.UUID
    user_id: uuid.UUID | None
    group_id: uuid.UUID | None
    scope_type: str | None
    scope_id: uuid.UUID | None
    conditions: dict
    role: RoleOut


@router.get("/role-bindings", response_model=list[BindingOut])
def list_bindings(ctx: Ctx = Depends(require("users:read"))):
    return ctx.db.scalars(select(RoleBinding).where(RoleBinding.tenant_id == ctx.tenant_id)).all()


@router.post("/role-bindings", response_model=BindingOut, status_code=201)
def create_binding(body: BindingIn, ctx: Ctx = Depends(require("users:write"))):
    if (body.user_id is None) == (body.group_id is None):
        raise HTTPException(422, "exactly one of user_id / group_id is required")
    if body.scope_type not in (None, "site", "device_group") or (body.scope_type is None) != (body.scope_id is None):
        raise HTTPException(422, "scope_type must be site|device_group together with scope_id")
    role = ctx.db.get(Role, body.role_id)
    if role is None or role.tenant_id not in (None, ctx.tenant_id):
        raise HTTPException(404, "role not found")
    if body.user_id:
        get_owned(ctx, User, body.user_id, "user")
    if body.group_id:
        get_owned(ctx, Group, body.group_id, "group")
    if not ctx.user.is_superuser and not {p.code for p in role.permissions} <= ctx.principal.permissions:
        raise HTTPException(403, "cannot grant a role with permissions you do not hold")
    b = RoleBinding(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(b)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="role.bind",
        actor=ctx.user,
        target_type="role_binding",
        target_id=b.id,
        target_name=role.name,
        after=body.model_dump(mode="json"),
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return b


@router.delete("/role-bindings/{binding_id}", status_code=204)
def delete_binding(binding_id: uuid.UUID, ctx: Ctx = Depends(require("users:write"))):
    b = get_owned(ctx, RoleBinding, binding_id, "binding")
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="role.unbind",
        actor=ctx.user,
        target_type="role_binding",
        target_id=b.id,
        target_name=b.role.name,
        before={"user_id": str(b.user_id), "group_id": str(b.group_id)},
        source_ip=ctx.ip,
    )
    ctx.db.delete(b)
    ctx.db.commit()


class LoginOut(ORM):
    id: uuid.UUID
    username: str
    timestamp: datetime
    success: bool
    method: str
    source_ip: str | None
    reason: str | None


@router.get("/login-history", response_model=Page[LoginOut])
def login_history(
    username: str | None = None,
    success: bool | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    ctx: Ctx = Depends(require("audit:read")),
):
    stmt = select(LoginHistory).where(LoginHistory.tenant_id == ctx.tenant_id).order_by(LoginHistory.timestamp.desc())
    if username:
        stmt = stmt.where(LoginHistory.username == username)
    if success is not None:
        stmt = stmt.where(LoginHistory.success.is_(success))
    return paginate(ctx.db, stmt, LoginOut, limit, offset)


# --- tenants (MSP operators) -----------------------------------------------------


class TenantIn(BaseModel):
    name: str
    slug: str
    admin_username: str = "admin"
    admin_password: str
    admin_email: EmailStr | None = None


class TenantOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    settings: dict = {}
    created_at: datetime


class TenantSettings(BaseModel):
    """Per-tenant overrides. ``None`` removes the override (global default applies)."""

    backup_sanitize_secrets: bool | None = None  # overrides NOM_BACKUP_SANITIZE_SECRETS
    restore_requires_change: bool | None = None  # real restores need an approved change (default true)


class TenantPatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    settings: TenantSettings | None = None


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(ctx: Ctx = Depends(require("tenants:admin"))):
    return ctx.db.scalars(select(Tenant).order_by(Tenant.name)).all()


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantIn, ctx: Ctx = Depends(require("tenants:admin"))):
    from app.services.bootstrap import create_tenant as svc_create

    if ctx.db.scalar(select(Tenant.id).where(or_(Tenant.slug == body.slug, Tenant.name == body.name))):
        raise HTTPException(409, "tenant already exists")
    try:
        t = svc_create(ctx.db, body.name, body.slug, body.admin_username, body.admin_password, body.admin_email)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit.record(
        ctx.db,
        tenant_id=ctx.principal.tenant_id,
        action="tenant.create",
        actor=ctx.user,
        target_type="tenant",
        target_id=t.id,
        target_name=t.slug,
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return t


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: uuid.UUID, body: TenantPatch, ctx: Ctx = Depends(require("tenants:admin"))):
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(404, "tenant not found")
    before = {"name": t.name, "is_active": t.is_active, "settings": dict(t.settings or {})}
    if body.name is not None:
        t.name = body.name
    if body.is_active is not None:
        if t.id == ctx.principal.tenant_id and not body.is_active:
            raise HTTPException(409, "cannot deactivate your own tenant")
        t.is_active = body.is_active
    if body.settings is not None:
        merged = dict(t.settings or {})
        for k, v in body.settings.model_dump(exclude_unset=True).items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        t.settings = merged
    audit.record(
        ctx.db,
        tenant_id=ctx.principal.tenant_id,
        action="tenant.update",
        actor=ctx.user,
        target_type="tenant",
        target_id=t.id,
        target_name=t.slug,
        before=before,
        after={"name": t.name, "is_active": t.is_active, "settings": t.settings},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return t
