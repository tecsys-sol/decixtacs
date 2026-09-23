"""RBAC catalogue + ABAC evaluation.

A user's effective permissions are the union of the roles bound to the user directly or via
their groups. A binding may carry a *scope* (site or device group) - such permissions only apply
to devices inside that scope - and ABAC ``conditions`` (vendor list, time window).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Device, Permission, Role, RoleBinding, User

PERMISSIONS: dict[str, str] = {
    "users:read": "View users, groups and roles",
    "users:write": "Create/modify users, groups, role bindings",
    "tenants:admin": "Manage tenants (platform operators)",
    "devices:read": "View inventory",
    "devices:write": "Modify inventory",
    "credentials:write": "Manage device credentials",
    "tacacs:read": "View TACACS configuration",
    "tacacs:write": "Modify TACACS policies, devices and users",
    "tacacs:deploy": "Render and deploy tac_plus-ng configuration",
    "configs:read": "View configuration backups and diffs",
    "configs:backup": "Trigger configuration backups",
    "configs:restore": "Restore / push configurations to devices",
    "configs:delete": "Delete configuration backups",
    "compliance:read": "View compliance results",
    "compliance:write": "Manage compliance rules and golden configs",
    "accounting:read": "Search TACACS command accounting",
    "sessions:read": "Replay recorded sessions",
    "audit:read": "View the audit trail",
    "changes:read": "View change requests",
    "changes:write": "Create and edit change requests",
    "changes:approve": "Approve or reject change requests",
    "integrations:write": "Configure NetBox / IXP Manager integrations",
    "alerts:write": "Manage alert channels and rules",
    "reports:read": "Generate reports",
}

BUILTIN_ROLES: dict[str, list[str]] = {
    "admin": list(PERMISSIONS),
    "network-engineer": [
        "devices:read", "devices:write", "tacacs:read", "configs:read", "configs:backup",
        "configs:restore", "compliance:read", "accounting:read", "sessions:read", "changes:read",
        "changes:write", "reports:read",
    ],
    "change-manager": ["devices:read", "configs:read", "changes:read", "changes:write", "changes:approve",
                       "audit:read", "reports:read"],
    "noc": ["devices:read", "configs:read", "compliance:read", "accounting:read", "changes:read"],
    "auditor": ["devices:read", "configs:read", "compliance:read", "accounting:read", "sessions:read",
                "audit:read", "changes:read", "tacacs:read", "reports:read", "users:read"],
    "read-only": ["devices:read", "configs:read", "compliance:read", "changes:read"],
}
BUILTIN_ROLES["admin"] = [p for p in PERMISSIONS if p != "tenants:admin"]


@dataclass
class Grant:
    permission: str
    scope_type: str | None = None
    scope_id: uuid.UUID | None = None
    conditions: dict = field(default_factory=dict)


@dataclass
class Principal:
    user: User
    grants: list[Grant]
    token_scopes: list[str] | None = None  # API token restriction

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.user.tenant_id

    def _visible(self, g: Grant) -> bool:
        return self.token_scopes is None or g.permission in self.token_scopes

    def has(self, permission: str) -> bool:
        """True if the permission is granted anywhere (possibly only on a scope)."""
        if self.user.is_superuser and (self.token_scopes is None or permission in self.token_scopes):
            return True
        return any(g.permission == permission and self._visible(g) and _conditions_ok(g.conditions) for g in self.grants)

    def has_global(self, permission: str) -> bool:
        if self.user.is_superuser and (self.token_scopes is None or permission in self.token_scopes):
            return True
        return any(
            g.permission == permission and g.scope_type is None and self._visible(g) and _conditions_ok(g.conditions)
            for g in self.grants
        )

    def can_on_device(self, permission: str, device: Device) -> bool:
        if self.has_global(permission):
            return True
        for g in self.grants:
            if g.permission != permission or not self._visible(g) or not _conditions_ok(g.conditions, device):
                continue
            if g.scope_type == "site" and device.site_id == g.scope_id:
                return True
            if g.scope_type == "device_group" and any(dg.id == g.scope_id for dg in device.groups):
                return True
            if g.scope_type is None:
                return True
        return False

    @property
    def permissions(self) -> set[str]:
        if self.user.is_superuser:
            base = set(PERMISSIONS)
        else:
            base = {g.permission for g in self.grants if _conditions_ok(g.conditions)}
        return base if self.token_scopes is None else base & set(self.token_scopes)


def _conditions_ok(conditions: dict, device: Device | None = None, now: datetime | None = None) -> bool:
    if not conditions:
        return True
    if device is not None and (vendors := conditions.get("vendor")):
        vendor = device.vendor.slug if device.vendor else None
        if vendor not in vendors:
            return False
    if hours := conditions.get("hours"):
        start_s, end_s = hours.split("-")
        now_t = (now or datetime.now()).time()
        start, end = time.fromisoformat(start_s), time.fromisoformat(end_s)
        inside = start <= now_t <= end if start <= end else (now_t >= start or now_t <= end)
        if not inside:
            return False
    return True


def load_principal(db: Session, user: User, token_scopes: list[str] | None = None) -> Principal:
    group_ids = [g.id for g in user.groups]
    stmt = select(RoleBinding).where(
        RoleBinding.tenant_id == user.tenant_id,
        or_(RoleBinding.user_id == user.id, RoleBinding.group_id.in_(group_ids) if group_ids else False),
    )
    grants: list[Grant] = []
    for binding in db.scalars(stmt):
        for perm in binding.role.permissions:
            grants.append(Grant(perm.code, binding.scope_type, binding.scope_id, binding.conditions or {}))
    return Principal(user=user, grants=grants, token_scopes=token_scopes)


def seed_rbac(db: Session) -> None:
    """Idempotently create the permission catalogue and built-in roles."""
    existing = {p.code: p for p in db.scalars(select(Permission))}
    for code, desc in PERMISSIONS.items():
        if code not in existing:
            existing[code] = Permission(code=code, description=desc)
            db.add(existing[code])
    db.flush()
    for name, codes in BUILTIN_ROLES.items():
        role = db.scalar(select(Role).where(Role.name == name, Role.tenant_id.is_(None)))
        if role is None:
            role = Role(name=name, builtin=True, description=f"Built-in {name} role")
            db.add(role)
        role.permissions = [existing[c] for c in codes]
    db.flush()
