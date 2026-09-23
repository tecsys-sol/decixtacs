"""Module 7 - parse tac_plus-ng access/authorization/accounting log lines.

The generator (``generator.py``: ``LOG_PREFIX``, ``ACCESS_FORMAT``, ``AUTHZ_FORMAT``,
``ACCT_FORMAT``) configures one tab separated layout for all three file destinations::

    TIMESTAMP  NAS  USER  PORT  CLIENT  RECORD-TYPE  key=value ...

Real lines written by tac_plus-ng with that configuration (tabs shown as ``<TAB>``)::

    2026-09-23 17:04:23 +0000<TAB>127.0.0.1<TAB>alice<TAB>tty1<TAB><TAB>AUTHC-PASS<TAB>service=login
        <TAB>authen-type=ascii<TAB>profile=noc-ro<TAB>session_id=893289eb<TAB>detail=shell login succeeded
    2026-09-23 17:04:25 +0000<TAB>127.0.0.1<TAB>alice<TAB>tty1<TAB><TAB>deny<TAB>service=shell<TAB>priv-lvl=0
        <TAB>profile=noc-ro<TAB>rule=noc-ro<TAB>session_id=8bcd49cc<TAB>cmd=show running-config <cr>
    2026-09-23 17:04:25 +0000<TAB>127.0.0.1<TAB>alice<TAB>tty1<TAB><TAB>stop<TAB>service=shell<TAB>priv-lvl=0
        <TAB>session_id=ffbaf7a0<TAB>args=task_id=42 priv-lvl=1 cmd=show cmd-arg=version<TAB>cmd=show version

The record type is ``start``/``stop``/``update`` (accounting), ``permit``/``deny`` (authorization)
or the tac_plus-ng message id ``AUTHC-PASS``/``AUTHC-FAIL-*`` (authentication); message ids of the
other kinds (``AUTHZ-PASS``, ``ACCT-STOP`` ...) are understood as well. The parser is positional for
the fixed prefix and treats everything after as ``attr=value`` pairs or free command text, so the
older ``TIMESTAMP NAS USER PORT CLIENT stop task_id=.. cmd=..`` layout keeps working, as does
tac_plus-ng's default file prefix ``"${TIMESTAMP} "`` (timestamp and NAS separated by a space).
A shipper (Vector, Fluent Bit, the bundled ``nom-tacacs-agent``) posts the lines to
``/api/v1/accounting/ingest``. JSON lines ({"timestamp":..., "user":..., ...}) are accepted too.
"""

from __future__ import annotations

import json
import re
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


# tac_plus-ng ${msgid} values -> record types used by the ingest
_MSGID_TYPES = {
    "acct-start": "start",
    "acct-stop": "stop",
    "acct-update": "update",
    "authz-pass": "permit",
    "authz-pass-add": "permit",
    "authz-pass-repl": "permit",
    "authz-fail": "deny",
}
_TS_NAS = re.compile(r"^(?P<ts>.+?) (?P<nas>[0-9A-Fa-f.:]+)$")
_AV = re.compile(r"(?:^| )([A-Za-z_][\w-]*)=(\S*)")


def _split_ts(field: str) -> tuple[str, str] | None:
    """``"2026-09-23 10:01:02 +0000 10.0.0.1"`` -> (timestamp, NAS) if the field is not a timestamp."""
    if "." not in field and ":" not in field:
        return None
    try:
        _parse_ts(field)
        return None
    except ValueError:
        pass
    m = _TS_NAS.match(field.strip())
    if not m:
        return None
    try:
        _parse_ts(m["ts"])
    except ValueError:
        return None
    return m["ts"], m["nas"]


def _av_pairs(args: str) -> dict[str, str]:
    """``${args, }`` ("task_id=42 priv-lvl=1 cmd=show ...") -> first value per attribute."""
    out: dict[str, str] = {}
    for k, v in _AV.findall(args or ""):
        out.setdefault(k, v)
    return out


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
    if len(parts) >= 5 and _split_ts(parts[0]):
        # tac_plus-ng's default file prefix is "${TIMESTAMP} " - timestamp and NAS share a field
        parts[0:1] = list(_split_ts(parts[0]))
    if len(parts) < 6:
        return None
    ts, nas, user, port, client, rtype, *rest = parts
    rtype_l = _MSGID_TYPES.get(rtype.strip().lower(), rtype.strip().lower())
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
    nas_args = _av_pairs(attrs.get("args", ""))
    if rtype_l in ACCT_TYPES:
        kind = "acct"
    elif rtype_l in AUTHZ_RESULTS or rtype_l.startswith(("permit", "deny", "authz-")):
        kind = "author"
    else:
        kind = "authen"
        if not command:
            command = attrs.get("detail", "")
    # the NAS-supplied priv-lvl AV pair wins over the packet header's privilege level
    priv = nas_args.get("priv-lvl") or attrs.get("priv-lvl") or attrs.get("priv_lvl")
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
        task_id=attrs.get("task_id") or nas_args.get("task_id"),
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
