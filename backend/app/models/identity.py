"""Module 1 (users/RBAC) and Module 19 (multi-tenancy)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk, utcnow


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(128), unique=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)


user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username"),)

    username: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_history: Mapped[list] = mapped_column(JSONType, default=list)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_source: Mapped[str] = mapped_column(String(16), default="local")  # local|ldap|ad|oidc
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)  # platform-wide operator
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    # last accepted TOTP time-step; codes at or before it are rejected (replay protection)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    groups: Mapped[list[Group]] = relationship(secondary=user_groups, back_populates="users")
    role_bindings: Mapped[list[RoleBinding]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="RoleBinding.user_id"
    )


class Group(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="local")  # local|ldap|ad|oidc
    external_dn: Mapped[str | None] = mapped_column(String(512))

    users: Mapped[list[User]] = relationship(secondary=user_groups, back_populates="groups")
    role_bindings: Mapped[list[RoleBinding]] = relationship(
        back_populates="group", cascade="all, delete-orphan", foreign_keys="RoleBinding.group_id"
    )


class Permission(UUIDPk, Base):
    """Global catalogue of permission codes such as ``devices:write``."""

    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Role(UUIDPk, Timestamps, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    # NULL tenant = built-in role shared by all tenants
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions)


class RoleBinding(UUIDPk, Timestamps, TenantScoped, Base):
    """Grants a role to a user or group, optionally scoped (ABAC) to a device group or site."""

    __tablename__ = "role_bindings"

    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("groups.id", ondelete="CASCADE"))
    scope_type: Mapped[str | None] = mapped_column(String(32))  # None|site|device_group
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Extra ABAC conditions, e.g. {"vendor": ["juniper"], "hours": "08:00-20:00"}
    conditions: Mapped[dict] = mapped_column(JSONType, default=dict)

    role: Mapped[Role] = relationship()
    user: Mapped[User | None] = relationship(back_populates="role_bindings", foreign_keys=[user_id])
    group: Mapped[Group | None] = relationship(back_populates="role_bindings", foreign_keys=[group_id])


class LoginHistory(UUIDPk, TenantScoped, Base):
    __tablename__ = "login_history"

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    username: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    method: Mapped[str] = mapped_column(String(16))  # password|ldap|oidc|api_token|refresh
    source_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    reason: Mapped[str | None] = mapped_column(String(255))


class RefreshToken(UUIDPk, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)  # rotation family for reuse detection
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ApiToken(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    token_prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSONType, default=list)  # subset of the user's permissions
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
