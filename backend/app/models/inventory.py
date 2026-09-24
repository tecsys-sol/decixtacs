"""Module 3 (inventory), Module 12 (device groups), Module 13 (topology links)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk

device_group_members = Table(
    "device_group_members",
    Base.metadata,
    Column("device_id", Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("device_group_id", Uuid, ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True),
)


class Region(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128))


class Site(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128))
    region_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("regions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32), default="pop")  # pop|datacenter|office|ixp
    address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    netbox_id: Mapped[int | None] = mapped_column(Integer, index=True)

    racks: Mapped[list[Rack]] = relationship(back_populates="site", cascade="all, delete-orphan")


class Rack(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "racks"
    name: Mapped[str] = mapped_column(String(255))
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    u_height: Mapped[int] = mapped_column(Integer, default=42)
    netbox_id: Mapped[int | None] = mapped_column(Integer, index=True)
    site: Mapped[Site] = relationship(back_populates="racks")


class Vendor(UUIDPk, Base):
    __tablename__ = "vendors"
    name: Mapped[str] = mapped_column(String(128), unique=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True)


class Platform(UUIDPk, Base):
    """Software platform (junos, eos, ios, nxos, fortios, sfos, routeros, vyos, linux).

    Carries the data-driven collection recipe so new platforms need no code changes.
    """

    __tablename__ = "platforms"
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vendors.id"))
    scrapli_platform: Mapped[str | None] = mapped_column(String(64))
    netmiko_device_type: Mapped[str | None] = mapped_column(String(64))
    backup_commands: Mapped[list] = mapped_column(JSONType, default=list)
    tacacs_service: Mapped[str] = mapped_column(String(32), default="shell")
    supports_tacacs: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_config_replace: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor: Mapped[Vendor | None] = relationship()


class DeviceModel(UUIDPk, Base):
    __tablename__ = "device_models"
    __table_args__ = (UniqueConstraint("vendor_id", "name"),)
    vendor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vendors.id"))
    name: Mapped[str] = mapped_column(String(255))
    vendor: Mapped[Vendor] = relationship()


class Credential(UUIDPk, Timestamps, TenantScoped, Base):
    """Device login credential; secrets encrypted at rest with MultiFernet."""

    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str] = mapped_column(String(128))
    password_enc: Mapped[str | None] = mapped_column(Text)
    ssh_key_enc: Mapped[str | None] = mapped_column(Text)
    enable_secret_enc: Mapped[str | None] = mapped_column(Text)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("tenant_id", "hostname"),)

    hostname: Mapped[str] = mapped_column(String(128), index=True)
    management_ip: Mapped[str] = mapped_column(String(64), index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id", ondelete="SET NULL"), index=True)
    rack_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("racks.id", ondelete="SET NULL"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vendors.id"))
    platform_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("platforms.id"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_models.id"))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("credentials.id", ondelete="SET NULL"))
    serial: Mapped[str | None] = mapped_column(String(128), index=True)
    os_version: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str | None] = mapped_column(String(128))  # core|edge|route-server|firewall|ce|switch
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|planned|offline|decommissioning
    reachability: Mapped[str] = mapped_column(String(16), default="unknown")  # up|down|unknown
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSONType, default=dict)
    netbox_id: Mapped[int | None] = mapped_column(Integer, index=True)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_backup_status: Mapped[str | None] = mapped_column(String(16))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    site: Mapped[Site | None] = relationship()
    platform: Mapped[Platform | None] = relationship()
    vendor: Mapped[Vendor | None] = relationship()
    model: Mapped[DeviceModel | None] = relationship()
    credential: Mapped[Credential | None] = relationship()
    groups: Mapped[list[DeviceGroup]] = relationship(secondary=device_group_members, back_populates="devices")


class DeviceGroup(UUIDPk, Timestamps, TenantScoped, Base):
    """Logical grouping: region, POP, customer edge, route servers, core routers, firewalls ...

    ``dynamic_filter`` allows rule-based membership, e.g. {"role": "route-server", "platform": "junos"}.
    """

    __tablename__ = "device_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), default="custom")
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_groups.id", ondelete="SET NULL"))
    dynamic_filter: Mapped[dict | None] = mapped_column(JSONType)
    devices: Mapped[list[Device]] = relationship(secondary=device_group_members, back_populates="groups")


class Link(UUIDPk, Timestamps, TenantScoped, Base):
    """Physical/logical link for the topology map (from NetBox cables or LLDP)."""

    __tablename__ = "links"
    a_device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    a_interface: Mapped[str] = mapped_column(String(128))
    b_device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    b_interface: Mapped[str] = mapped_column(String(128))
    speed_mbps: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="up")
    source: Mapped[str] = mapped_column(String(16), default="netbox")
