"""Modules 4-6, 11 + config intelligence and drift."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk, utcnow


class ConfigBackup(UUIDPk, TenantScoped, Base):
    """One row per collection attempt. Content lives in Git; ``commit_sha`` points at it."""

    __tablename__ = "config_backups"
    __table_args__ = (Index("ix_config_backups_device_time", "device_id", "collected_at"),)

    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(16))  # success|unchanged|failed
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), index=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str | None] = mapped_column(String(128))  # from TACACS accounting correlation
    reason: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")  # schedule|manual|change|syslog
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("change_requests.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    risk_score: Mapped[int | None] = mapped_column(Integer)
    device = relationship("Device")


class GoldenConfig(UUIDPk, Timestamps, TenantScoped, Base):
    """Intended configuration for drift detection: pinned to a device or a device group."""

    __tablename__ = "golden_configs"
    name: Mapped[str] = mapped_column(String(128))
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"))
    device_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_groups.id", ondelete="CASCADE"))
    # "full" = entire config must match; "snippet" = these lines must be present
    mode: Mapped[str] = mapped_column(String(16), default="snippet")
    content: Mapped[str] = mapped_column(Text)
    ignore_patterns: Mapped[list] = mapped_column(JSONType, default=list)


class DriftEvent(UUIDPk, TenantScoped, Base):
    __tablename__ = "drift_events"
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # running_vs_backup|backup_vs_golden
    diff: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceRule(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "compliance_rules"
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    # must_match | must_not_match | block_must_match | count_at_least
    rule_type: Mapped[str] = mapped_column(String(32))
    pattern: Mapped[str] = mapped_column(Text)
    block_start: Mapped[str | None] = mapped_column(String(512))  # regex opening a config block
    min_count: Mapped[int] = mapped_column(Integer, default=1)
    platforms: Mapped[list] = mapped_column(JSONType, default=list)  # empty = all
    device_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("device_groups.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high|critical
    remediation: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ComplianceRun(UUIDPk, TenantScoped, Base):
    __tablename__ = "compliance_runs"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devices_checked: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float)  # tenant-wide weighted score 0-100


class ComplianceResult(UUIDPk, TenantScoped, Base):
    __tablename__ = "compliance_results"
    __table_args__ = (Index("ix_compliance_results_run_device", "run_id", "device_id"),)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("compliance_runs.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("compliance_rules.id", ondelete="CASCADE"))
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str | None] = mapped_column(Text)
    backup_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("config_backups.id", ondelete="SET NULL"))


class DeviceComplianceScore(UUIDPk, TenantScoped, Base):
    __tablename__ = "device_compliance_scores"
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("compliance_runs.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[int] = mapped_column(Integer)
    failed: Mapped[int] = mapped_column(Integer)


class ConfigIndexEntry(UUIDPk, TenantScoped, Base):
    """Parsed, searchable config objects (BGP neighbours, communities, prefix-lists, filters ...)."""

    __tablename__ = "config_index"
    __table_args__ = (
        Index("ix_config_index_kind_key", "tenant_id", "kind", "key"),
        Index("ix_config_index_device", "device_id"),
    )
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"))
    backup_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("config_backups.id", ondelete="SET NULL"))
    # interface|routing_instance|bgp_group|bgp_neighbor|community|prefix_list|firewall_filter|policy
    kind: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(255))  # primary lookup value (neighbor IP, community name ...)
    attributes: Mapped[dict] = mapped_column(JSONType, default=dict)


class ConfigRestore(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "config_restores"
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    backup_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("config_backups.id"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("change_requests.id", ondelete="SET NULL")
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|diffed|pushed|failed|rolled_back
    device_diff: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    pre_restore_backup_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class RancidConfig(UUIDPk, TenantScoped, Base):
    """Last configuration RANCID stored for a router, imported to compare with NOM's own backup."""

    __tablename__ = "rancid_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(255))  # the router.db / configs/ file name
    rancid_group: Mapped[str | None] = mapped_column(String(128))
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    content: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device = relationship("Device")
