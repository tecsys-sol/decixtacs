"""Module 2 - TACACS+ management (tac_plus-ng)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk


class TacacsServer(UUIDPk, Timestamps, TenantScoped, Base):
    """A tac_plus-ng instance. Config is rendered from the DB and pushed/pulled by the agent sidecar."""

    __tablename__ = "tacacs_servers"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(64))
    port: Mapped[int] = mapped_column(Integer, default=49)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # LDAP/AD backend via MAVIS for users with auth_source=ldap
    ldap_backend: Mapped[bool] = mapped_column(Boolean, default=False)
    config_version: Mapped[int] = mapped_column(Integer, default=0)
    config_sha256: Mapped[str | None] = mapped_column(String(64))
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # reported by the agent on every heartbeat: what tac_plus-ng runs and whether the last apply worked
    running_sha256: Mapped[str | None] = mapped_column(String(64))
    agent_status: Mapped[str | None] = mapped_column(String(16))  # ok|error
    agent_message: Mapped[str | None] = mapped_column(Text)
    agent_token_hash: Mapped[str | None] = mapped_column(String(64))


class TacacsDevice(UUIDPk, Timestamps, TenantScoped, Base):
    """NAS client entry: an inventory device or a whole prefix sharing a key."""

    __tablename__ = "tacacs_devices"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(128))
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(String(64))  # IP or CIDR
    key_enc: Mapped[str] = mapped_column(Text)
    vendor: Mapped[str] = mapped_column(String(32))  # juniper|cisco|arista|fortinet|sophos|mikrotik|generic
    device_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_groups.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TacacsPolicy(UUIDPk, Timestamps, TenantScoped, Base):
    """Authorization profile (tac_plus-ng ``profile``): privilege + vendor attributes + command set.

    Bound to a platform group (who) and optionally a device group (where).
    """

    __tablename__ = "tacacs_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = evaluated first
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("groups.id", ondelete="CASCADE"))
    device_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_groups.id", ondelete="CASCADE"))
    privilege_level: Mapped[int] = mapped_column(Integer, default=1)
    junos_class: Mapped[str | None] = mapped_column(String(64))  # local-user-name template on Junos
    fortigate_profile: Mapped[str | None] = mapped_column(String(64))  # admin_prof
    arista_role: Mapped[str | None] = mapped_column(String(64))
    extra_attributes: Mapped[dict] = mapped_column(JSONType, default=dict)  # vendor -> {attr: value}
    default_action: Mapped[str] = mapped_column(String(8), default="deny")  # for unmatched commands
    time_window: Mapped[str | None] = mapped_column(String(32))  # e.g. "Mon-Fri 08:00-20:00"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    command_rules: Mapped[list[TacacsCommandPolicy]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", order_by="TacacsCommandPolicy.sequence"
    )


class TacacsCommandPolicy(UUIDPk, TenantScoped, Base):
    __tablename__ = "tacacs_command_policies"
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tacacs_policies.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    action: Mapped[str] = mapped_column(String(8))  # permit|deny
    pattern: Mapped[str] = mapped_column(String(512))  # POSIX regex matched against full command line
    description: Mapped[str | None] = mapped_column(Text)
    alert_on_match: Mapped[bool] = mapped_column(Boolean, default=False)
    policy: Mapped[TacacsPolicy] = relationship(back_populates="command_rules")


class TacacsUserMapping(UUIDPk, Timestamps, TenantScoped, Base):
    """Which platform users exist on the TACACS servers and how they authenticate."""

    __tablename__ = "tacacs_user_mappings"
    __table_args__ = (UniqueConstraint("tenant_id", "tacacs_username"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tacacs_username: Mapped[str] = mapped_column(String(64))
    # "crypt" = local SHA-512 crypt hash, "ldap" = MAVIS LDAP backend
    auth_method: Mapped[str] = mapped_column(String(16), default="crypt")
    password_crypt: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user = relationship("User")


class TacacsConfigRevision(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "tacacs_config_revisions"
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tacacs_servers.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)  # stored with keys redacted; the agent fetches a fresh render
    generated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
