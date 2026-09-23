"""Module 7 - parse tac_plus-ng access/authorization/accounting log lines.

The file/syslog destinations configured by the generator emit tab separated records::

    2026-09-23 10:01:02 +0000<TAB>10.0.0.1<TAB>shashank<TAB>ssh<TAB>192.0.2.10<TAB>stop<TAB>task_id=7<TAB>service=shell<TAB>cmd=show version <cr>

Field layout differs slightly between versions and between the accounting and authorization logs,
so the parser is positional for the fixed prefix (time, NAS, user, port, client, record type) and
treats everything after as either ``attr=value`` pairs or the command text. A shipper (Vector,
Fluent Bit, the bundled ``nom-tacacs-agent``) posts the lines to ``/api/v1/accounting/ingest``.
JSON lines ({"timestamp":..., "user":..., ...}) are accepted too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

ACCT_TYPES = {"start", "stop", "update", "watchdog"}
AUTHZ_RESULTS = {"permit", "deny", "fail", "pass", "error"}


@dataclass
class ParsedRecord:
    kind: str  # acct|author|authen
    timestamp: datetime
    device_address: str
    username: str
    port: str | None
    source_address: str | None
    record_type: str
    command: str
    service: str | None = None
    priv_lvl: int | None = None
    task_id: str | None = None
    session_id: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    raw: str = ""


def _parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%b %d %H:%M:%S"):
        try:
            ts = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        if fmt == "%b %d %H:%M:%S":
            ts = ts.replace(year=datetime.now(UTC).year)
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    try:
        ts = datetime.fromisoformat(value.strip())
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp: {value!r}") from exc


def _clean_cmd(cmd: str) -> str:
    cmd = cmd.strip()
    if cmd.endswith("<cr>"):
        cmd = cmd[: -len("<cr>")].rstrip()
    return cmd


def parse_line(line: str) -> ParsedRecord | None:
    line = line.rstrip("\r\n")
    if not line.strip():
        return None
    if line.lstrip().startswith("{"):
        return _parse_json(line)
    parts = line.split("\t")
    if len(parts) < 6:
        return None
    ts, nas, user, port, client, rtype, *rest = parts
    rtype_l = rtype.strip().lower()
    attrs: dict[str, str] = {}
    free: list[str] = []
    for item in rest:
        k, sep, v = item.partition("=")
        if sep and k and " " not in k:
            attrs[k.strip()] = v
        elif item.strip():
            free.append(item)
    command = attrs.pop("cmd", None) or " ".join(free)
    # Junos sends cmd-arg-N style or "cmd" + args; also accept "cmd-arg"
    args = [attrs.pop(k) for k in sorted([k for k in attrs if k.startswith("cmd-arg")])]
    if args:
        command = " ".join([command, *args]).strip()
    if rtype_l in ACCT_TYPES:
        kind = "acct"
    elif rtype_l in AUTHZ_RESULTS or rtype_l.startswith(("permit", "deny")):
        kind = "author"
    else:
        kind = "authen"
    priv = attrs.get("priv-lvl") or attrs.get("priv_lvl")
    return ParsedRecord(
        kind=kind,
        timestamp=_parse_ts(ts),
        device_address=nas.strip(),
        username=user.strip(),
        port=port.strip() or None,
        source_address=client.strip() or None,
        record_type=rtype_l,
        command=_clean_cmd(command),
        service=attrs.get("service"),
        priv_lvl=int(priv) if priv and priv.isdigit() else None,
        task_id=attrs.get("task_id"),
        session_id=attrs.get("session_id") or attrs.get("session-id"),
        attributes=attrs,
        raw=line,
    )


def _parse_json(line: str) -> ParsedRecord | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    rtype = str(d.get("type") or d.get("acct_type") or d.get("result") or "stop").lower()
    kind = d.get("kind") or ("acct" if rtype in ACCT_TYPES else "author" if rtype in AUTHZ_RESULTS else "authen")
    return ParsedRecord(
        kind=kind,
        timestamp=_parse_ts(str(d.get("timestamp") or d.get("time"))),
        device_address=str(d.get("device") or d.get("nas") or d.get("device_address")),
        username=str(d.get("user") or d.get("username")),
        port=d.get("port"),
        source_address=d.get("client") or d.get("source_address"),
        record_type=rtype,
        command=_clean_cmd(str(d.get("cmd") or d.get("command") or "")),
        service=d.get("service"),
        priv_lvl=d.get("priv_lvl"),
        task_id=d.get("task_id"),
        session_id=d.get("session_id"),
        raw=line,
    )
