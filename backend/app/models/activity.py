"""Modules 7 (accounting), 8 (session recording), 9 (audit), 10 (change management).

``command_logs`` and ``audit_events`` are range-partitioned by month on PostgreSQL
(see alembic migration 0002); hence the composite primary key including the timestamp.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TenantScoped, Timestamps, UUIDPk, utcnow


class CommandLog(TenantScoped, Base):
    __tablename__ = "command_logs"
    __table_args__ = (
        Index("ix_command_logs_user_ts", "username", "timestamp"),
        Index("ix_command_logs_device_ts", "device_address", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    username: Mapped[str] = mapped_column(String(64))
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # soft ref: partitions avoid FK fan-in
    device_address: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str | None] = mapped_column(String(128))
    source_address: Mapped[str | None] = mapped_column(String(64))
    port: Mapped[str | None] = mapped_column(String(32))
    service: Mapped[str | None] = mapped_column(String(32))
    record_type: Mapped[str] = mapped_column(String(8), default="stop")  # start|stop|update
    command: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(16), default="accounted")  # permitted|denied|accounted
    priv_lvl: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    raw: Mapped[str | None] = mapped_column(Text)


class TacacsAuthEvent(TenantScoped, Base):
    """Authentication/authorization decisions from the tac_plus-ng access log."""

    __tablename__ = "tacacs_auth_events"
    __table_args__ = (Index("ix_tacacs_auth_events_ts", "timestamp"), {"postgresql_partition_by": "RANGE (timestamp)"})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    username: Mapped[str] = mapped_column(String(64), index=True)
    device_address: Mapped[str] = mapped_column(String(64))
    source_address: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # authen|author
    result: Mapped[str] = mapped_column(String(16))  # pass|fail|permit|deny
    detail: Mapped[str | None] = mapped_column(Text)


class SessionRecording(UUIDPk, TenantScoped, Base):
    """asciicast v2 recording captured by the SSH bastion/recorder."""

    __tablename__ = "session_recordings"
    username: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    device_address: Mapped[str] = mapped_column(String(64))
    source_address: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None]
    storage_uri: Mapped[str] = mapped_column(String(512))  # file:// or s3://
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    commands: Mapped[list] = mapped_column(JSONType, default=list)  # extracted command index for search
    tacacs_session_id: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(TenantScoped, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_actor_ts", "actor_id", "timestamp"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)  # e.g. user.create, config.restore
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    target_name: Mapped[str | None] = mapped_column(String(255))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    # Tamper evidence: sha256(prev_hash + canonical event)
    chain_hash: Mapped[str | None] = mapped_column(String(64))


class ChangeRequest(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "change_requests"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # draft|pending_approval|approved|rejected|implemented|closed|cancelled
    state: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    risk: Mapped[str] = mapped_column(String(16), default="medium")
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_ids: Mapped[list] = mapped_column(JSONType, default=list)
    implementation_plan: Mapped[str | None] = mapped_column(Text)
    rollback_plan: Mapped[str | None] = mapped_column(Text)
    pre_backup_ids: Mapped[list] = mapped_column(JSONType, default=list)
    post_backup_ids: Mapped[list] = mapped_column(JSONType, default=list)
    external_ticket: Mapped[str | None] = mapped_column(String(128))


class ChangeRequestComment(UUIDPk, TenantScoped, Base):
    __tablename__ = "change_request_comments"
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("change_requests.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    body: Mapped[str] = mapped_column(Text)
    transition: Mapped[str | None] = mapped_column(String(48))
