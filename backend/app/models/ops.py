"""Modules 14-18: integrations mirror tables, route-server awareness, alerting and reports."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk, utcnow


class Integration(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "name"),)
    kind: Mapped[str] = mapped_column(String(32))  # netbox|ixpmanager|birdseye|prometheus
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))
    token_enc: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(16))
    last_sync_detail: Mapped[dict | None] = mapped_column(JSONType)


class ExternalObject(UUIDPk, TenantScoped, Base):
    """Mirror of NetBox/IXP Manager objects not modelled natively (VLANs, prefixes, VRFs, ASNs, contacts)."""

    __tablename__ = "external_objects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "object_type", "external_id"),
        Index("ix_external_objects_type", "tenant_id", "object_type"),
    )
    source: Mapped[str] = mapped_column(String(32))
    object_type: Mapped[str] = mapped_column(String(32))  # vlan|prefix|ip|vrf|asn|contact|...
    external_id: Mapped[str] = mapped_column(String(64))
    display: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IxpMember(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "ixp_members"
    __table_args__ = (UniqueConstraint("tenant_id", "asn"),)
    asn: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(512))
    peering_policy: Mapped[str | None] = mapped_column(String(32))
    member_type: Mapped[str | None] = mapped_column(String(32))
    contacts: Mapped[list] = mapped_column(JSONType, default=list)
    connections: Mapped[list] = mapped_column(JSONType, default=list)  # ports, speed, vlans, IPs
    traffic: Mapped[dict] = mapped_column(JSONType, default=dict)


class RouteServerClient(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "route_server_clients"
    __table_args__ = (UniqueConstraint("tenant_id", "route_server", "protocol_name"),)
    route_server: Mapped[str] = mapped_column(String(64))
    protocol_name: Mapped[str] = mapped_column(String(128))
    asn: Mapped[int] = mapped_column(BigInteger, index=True)
    neighbor_address: Mapped[str] = mapped_column(String(64))
    address_family: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(32))
    prefixes_accepted: Mapped[int] = mapped_column(Integer, default=0)
    prefixes_filtered: Mapped[int] = mapped_column(Integer, default=0)
    prefixes_exported: Mapped[int] = mapped_column(Integer, default=0)
    irr_filtered: Mapped[int] = mapped_column(Integer, default=0)
    rpki_invalid: Mapped[int] = mapped_column(Integer, default=0)
    rpki_status: Mapped[dict] = mapped_column(JSONType, default=dict)  # {valid, invalid, unknown}
    irr_status: Mapped[str | None] = mapped_column(String(32))
    since: Mapped[str | None] = mapped_column(String(64))


class AlertChannel(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "alert_channels"
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # email|slack|teams|webhook
    target_enc: Mapped[str] = mapped_column(Text)  # URL or comma separated addresses (encrypted)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertRule(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "alert_rules"
    name: Mapped[str] = mapped_column(String(128))
    # backup_failed|device_unreachable|unauthorized_command|compliance_failure|config_drift|login_failed
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    min_severity: Mapped[str] = mapped_column(String(16), default="low")
    channel_ids: Mapped[list] = mapped_column(JSONType, default=list)
    filters: Mapped[dict] = mapped_column(JSONType, default=dict)
    throttle_minutes: Mapped[int] = mapped_column(Integer, default=15)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(UUIDPk, TenantScoped, Base):
    __tablename__ = "alerts"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="SET NULL"))
    dedup_key: Mapped[str | None] = mapped_column(String(255), index=True)
    delivered: Mapped[list] = mapped_column(JSONType, default=list)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportSchedule(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "report_schedules"
    name: Mapped[str] = mapped_column(String(128))
    report_type: Mapped[str] = mapped_column(String(32))  # device_changes|user_activity|config_changes|compliance|tacacs
    period: Mapped[str] = mapped_column(String(16))  # daily|weekly|monthly
    fmt: Mapped[str] = mapped_column(String(8), default="pdf")
    recipients: Mapped[list] = mapped_column(JSONType, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
