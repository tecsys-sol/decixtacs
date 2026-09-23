"""Typed response models (mirroring the API's Pydantic schemas).

Models are frozen dataclasses built with :func:`parse`, which ignores unknown fields (forward
compatible with newer servers) and converts ISO-8601 timestamps and UUIDs. The untouched JSON is
available as ``raw`` on every model.
"""

from __future__ import annotations

import dataclasses
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")
M = TypeVar("M", bound="Model")


@dataclass(frozen=True)
class Model:
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False, kw_only=True)


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return _convert(args[0], value) if len(args) == 1 else value
    if tp is datetime and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if tp is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if origin is list and isinstance(value, list):
        (inner,) = get_args(tp) or (Any,)
        return [_convert(inner, v) for v in value]
    if isinstance(tp, type) and issubclass(tp, Model) and isinstance(value, dict):
        return parse(tp, value)
    return value


def parse(cls: type[M], data: dict[str, Any]) -> M:
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name == "raw":
            continue
        if f.name in data:
            kwargs[f.name] = _convert(hints[f.name], data[f.name])
    return cls(**kwargs, raw=data)


# --- common -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass(frozen=True)
class Ref(Model):
    id: uuid.UUID
    name: str = ""


@dataclass(frozen=True)
class PlatformRef(Model):
    id: uuid.UUID
    slug: str = ""
    name: str = ""


@dataclass(frozen=True)
class TokenPair(Model):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


@dataclass(frozen=True)
class Me(Model):
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    email: str | None = None
    full_name: str | None = None
    is_superuser: bool = False
    mfa_enabled: bool = False
    auth_source: str = "local"
    permissions: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


# --- inventory ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Device(Model):
    id: uuid.UUID
    hostname: str
    management_ip: str
    status: str = "active"
    reachability: str = "unknown"
    site: Ref | None = None
    platform: PlatformRef | None = None
    vendor: Ref | None = None
    serial: str | None = None
    os_version: str | None = None
    role: str | None = None
    backup_enabled: bool = True
    ssh_port: int = 22
    tags: list[str] = field(default_factory=list)
    netbox_id: int | None = None
    credential_id: uuid.UUID | None = None
    last_backup_at: datetime | None = None
    last_backup_status: str | None = None
    groups: list[Ref] = field(default_factory=list)
    created_at: datetime | None = None


# --- configuration backups ------------------------------------------------------------------------


@dataclass(frozen=True)
class Backup(Model):
    id: uuid.UUID
    device_id: uuid.UUID
    collected_at: datetime
    status: str  # success | unchanged | failed
    changed: bool = False
    commit_sha: str | None = None
    size_bytes: int | None = None
    lines_added: int = 0
    lines_removed: int = 0
    author: str | None = None
    reason: str | None = None
    trigger: str = "schedule"
    change_request_id: uuid.UUID | None = None
    error: str | None = None
    duration_ms: int | None = None
    risk_score: int | None = None


@dataclass(frozen=True)
class Diff(Model):
    old_rev: str
    new_rev: str
    unified: str
    added: int
    removed: int
    side_by_side: list[dict[str, Any]] = field(default_factory=list)
    inline: list[dict[str, Any]] | None = None
    risk: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Restore(Model):
    id: uuid.UUID
    device_id: uuid.UUID
    backup_id: uuid.UUID
    dry_run: bool
    status: str  # diffed | pushed | failed
    device_diff: str | None = None
    output: str | None = None
    pre_restore_backup_id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class DriftEvent(Model):
    id: uuid.UUID
    device_id: uuid.UUID
    detected_at: datetime
    kind: str
    diff: str
    resolved: bool = False


# --- TACACS+ ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TacacsServer(Model):
    id: uuid.UUID
    name: str
    address: str
    port: int = 49
    enabled: bool = True
    ldap_backend: bool = False
    config_version: int = 0
    config_sha256: str | None = None
    last_deployed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    agent_token: str | None = None  # only present in the create response


@dataclass(frozen=True)
class RenderResult(Model):
    sha256: str
    content: str  # NAS keys / LDAP password redacted
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigRevision(Model):
    id: uuid.UUID
    server_id: uuid.UUID
    version: int
    sha256: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class NasClient(Model):
    id: uuid.UUID
    name: str
    address: str
    vendor: str
    device_id: uuid.UUID | None = None
    device_group_id: uuid.UUID | None = None
    enabled: bool = True
    key_rotated_at: datetime | None = None


@dataclass(frozen=True)
class AuthEvent(Model):
    id: uuid.UUID
    timestamp: datetime
    username: str
    device_address: str
    kind: str
    result: str
    source_address: str | None = None
    detail: str | None = None


# --- accounting ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandRecord(Model):
    id: uuid.UUID
    timestamp: datetime
    username: str
    device_address: str
    command: str
    result: str
    record_type: str = "stop"
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    source_address: str | None = None
    service: str | None = None
    priv_lvl: int | None = None
    dangerous: str | None = None


# --- compliance ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplianceRule(Model):
    id: uuid.UUID
    name: str
    rule_type: str
    pattern: str
    severity: str = "medium"
    description: str | None = None
    block_start: str | None = None
    min_count: int = 1
    platforms: list[str] = field(default_factory=list)
    device_group_id: uuid.UUID | None = None
    remediation: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ComplianceRun(Model):
    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    devices_checked: int = 0
    score: float | None = None


# --- changes ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeRequest(Model):
    id: uuid.UUID
    number: int
    title: str
    state: str
    risk: str = "medium"
    description: str | None = None
    requested_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    implemented_at: datetime | None = None
    closed_at: datetime | None = None
    device_ids: list[str] = field(default_factory=list)
    implementation_plan: str | None = None
    rollback_plan: str | None = None
    pre_backup_ids: list[str] = field(default_factory=list)
    post_backup_ids: list[str] = field(default_factory=list)
    external_ticket: str | None = None
    created_at: datetime | None = None

    @property
    def key(self) -> str:
        return f"CHG-{self.number}"


# --- audit --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent(Model):
    id: uuid.UUID
    timestamp: datetime
    actor_name: str
    action: str
    outcome: str = "success"
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    source_ip: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


__all__ = [n for n, v in list(globals().items()) if isinstance(v, type) and issubclass(v, Model)] + [
    "Page", "parse"]
