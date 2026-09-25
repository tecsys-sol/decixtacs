"""Who changed which line: match diff rows against TACACS+ command accounting.

Between two stored revisions of a device, every configuration command an engineer typed is in
``command_logs``. Each added/removed/modified line of the diff is matched to the latest command
that produces it:

* Junos (``display set``): ``set X`` adds the line ``set X``, ``delete X`` / ``deactivate X``
  remove every line under ``set X``. ``edit``/``up``/``top``/``exit`` are tracked per session so
  relative commands typed inside a hierarchy resolve to the full path.
* Line-based CLIs (IOS, EOS, NX-OS, FortiOS, RouterOS ...): a command equal to the (indented) line
  adds it, ``no X`` removes it.

A line nobody's command explains is left unattributed, unless exactly one engineer issued
configuration commands in the window - then it is attributed to them as ``inferred``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CommandLog, Device

_WS = re.compile(r"\s+")
_CR = re.compile(r"\s*<cr>\s*$", re.I)
# commands that only navigate or show - never configuration changes
_NON_CONFIG = re.compile(
    r"^(show|ping|traceroute|trace|monitor|request|clear|file|help|exit|quit|end|commit|configure|"
    r"conf(ig)?( t(erminal)?)?|run |edit|top|up|rollback|compare|status|write|copy|terminal|enable|"
    r"disable|who|start shell|cli|diagnose|get |execute|/?quit)\b",
    re.I,
)
_JUNOS_VERBS = ("set", "delete", "deactivate", "activate", "replace", "insert", "annotate", "protect", "unprotect")
MAX_COMMANDS = 5000
STRUCTURAL = {"", "!", "#", "}", "exit", "end", "next"}


# entering/leaving configuration mode or committing: evidence someone configured the device even
# when the individual commands are not in the log (e.g. Junos without change-log accounting)
CONFIG_MODE = re.compile(
    r"^(configure|conf t|config(ure)? (terminal|private|exclusive)|commit|write( mem)?|copy run|rollback|load )", re.I
)


@dataclass
class Edit:
    username: str
    at: datetime
    command: str  # as logged
    full: str  # normalised, with the Junos edit path applied
    config_mode: bool = False  # only evidence of configuration activity, produces no line


def norm(text: str) -> str:
    return _WS.sub(" ", _CR.sub("", text or "")).strip()


def load_commands(db: Session, device: Device, since: datetime | None, until: datetime | None) -> list[CommandLog]:
    addr = [CommandLog.device_id == device.id]
    if device.management_ip:
        addr.append(CommandLog.device_address == device.management_ip)
    q = select(CommandLog).where(CommandLog.tenant_id == device.tenant_id, or_(*addr), CommandLog.result != "denied")
    if since is not None:
        q = q.where(CommandLog.timestamp > since - timedelta(seconds=60))
    if until is not None:
        q = q.where(CommandLog.timestamp <= until + timedelta(seconds=60))
    return list(db.scalars(q.order_by(CommandLog.timestamp).limit(MAX_COMMANDS)))


def expand(rows: list[CommandLog], junos: bool) -> list[Edit]:
    """Normalise commands, apply Junos ``edit`` paths per session, drop duplicates and non-config commands."""
    paths: dict[tuple, list[str]] = defaultdict(list)
    seen: set[tuple] = set()
    out: list[Edit] = []
    for r in rows:
        cmd = norm(r.command)
        if not cmd:
            continue
        key = (r.username, r.command, r.timestamp.replace(microsecond=0))
        if key in seen:  # start + stop accounting records of the same command
            continue
        seen.add(key)
        sess = (r.username, r.session_id or r.task_id or r.port or "")
        if CONFIG_MODE.match(cmd):
            out.append(Edit(r.username, r.timestamp, r.command, cmd, config_mode=True))
            continue
        if junos:
            words = cmd.split(" ")
            verb = words[0].lower()
            path = paths[sess]
            if verb == "edit":
                path.extend(words[1:])
                continue
            if verb == "top":
                if len(words) > 1:  # "top set ..." - absolute command
                    cmd, words, verb = " ".join(words[1:]), words[1:], words[1].lower()
                    path = []
                else:
                    path.clear()
                    continue
            if verb == "up":
                n = int(words[1]) if len(words) > 1 and words[1].isdigit() else 1
                del path[max(0, len(path) - n) :]
                continue
            if verb in ("exit", "quit"):
                if path:
                    path.pop()
                continue
            if verb in _JUNOS_VERBS:
                full = " ".join([verb, *path, *words[1:]])
                out.append(Edit(r.username, r.timestamp, r.command, full))
            continue
        if _NON_CONFIG.match(cmd):
            continue
        out.append(Edit(r.username, r.timestamp, r.command, cmd))
    return out


def _starts(line: str, prefix: str) -> bool:
    return line == prefix or line.startswith(prefix + " ")


def _adds(e: Edit, line: str, junos: bool) -> bool:
    if junos:
        verb, _, rest = e.full.partition(" ")
        verb = verb.lower()
        if verb == "set":
            return line == e.full
        if verb == "deactivate":
            return _starts(line, f"deactivate {rest}")
        if verb == "activate":  # re-activating shows the plain set lines again
            return _starts(line, f"set {rest}")
        return False
    return line == e.full


def _adds_suffix(e: Edit, line: str) -> bool:
    """Junos command typed inside an ``edit`` hierarchy we did not see (e.g. accounting started mid-session)."""
    verb, _, rest = e.full.partition(" ")
    return verb.lower() == "set" and bool(rest) and line.startswith("set ") and line.endswith(" " + rest)


def _removes(e: Edit, line: str, junos: bool, replace: bool = False) -> bool:
    verb, _, rest = e.full.partition(" ")
    verb = verb.lower()
    if replace:
        # a Junos set replaces the previous value of a single-valued leaf (description, mtu, ...)
        head = e.full.rpartition(" ")[0]
        return junos and verb == "set" and line != e.full and line.rpartition(" ")[0] == head and head.count(" ") >= 2
    if junos:
        if verb == "delete":
            return _starts(line, f"set {rest}") or _starts(line, f"deactivate {rest}")
        if verb == "deactivate":
            return _starts(line, f"set {rest}")
        if verb == "activate":
            return _starts(line, f"deactivate {rest}")
        return False
    if verb == "no":
        return _starts(line, rest)
    if verb in ("delete", "unset", "remove"):  # FortiOS unset/delete, RouterOS remove
        return rest != "" and rest in line
    return False


def _same_leaf(a: str, b: str) -> bool:
    wa, wb = norm(a).split(" "), norm(b).split(" ")
    return len(wa) > 1 and len(wa) == len(wb) and wa[:-1] == wb[:-1] or (wa[:1] == wb[:1] and wa[0] != "set")


def _by(e: Edit, confidence: str) -> dict:
    return {"user": e.username, "at": e.at.isoformat(), "command": e.command, "confidence": confidence}


def attribute(rows: list[dict], edits: list[Edit], junos: bool) -> list[dict]:
    """Annotate diff rows in place with ``right_by`` / ``left_by``; returns the per-engineer summary."""
    config_users = {e.username for e in edits}
    sole = next((e for e in reversed(edits)), None) if len(config_users) == 1 else None
    latest_first = [e for e in reversed(edits) if not e.config_mode]
    counts: dict[str, dict] = {}

    def find_add(line: str) -> dict | None:
        text = norm(line)
        for e in latest_first:
            if _adds(e, text, junos):
                return _by(e, "exact")
        if junos:
            for e in latest_first:
                if _adds_suffix(e, text):
                    return _by(e, "exact")
        return None

    def find_remove(line: str) -> dict | None:
        text = norm(line)
        for replace in (False, True):
            for e in latest_first:
                if _removes(e, text, junos, replace):
                    return _by(e, "exact")
        return None

    def bump(by: dict | None, side: str) -> None:
        if not by:
            return
        c = counts.setdefault(
            by["user"],
            {
                "username": by["user"],
                "added": 0,
                "removed": 0,
                "inferred": 0,
                "first_at": by["at"],
                "last_at": by["at"],
            },
        )
        c[side] += 1
        if by["confidence"] == "inferred":
            c["inferred"] += 1
        c["first_at"], c["last_at"] = min(c["first_at"], by["at"]), max(c["last_at"], by["at"])

    for r in rows:
        t = r.get("type")
        if t not in ("added", "removed", "modified"):
            continue
        if all(norm(r.get(k) or "") in STRUCTURAL for k in ("left", "right")):
            continue  # separators / block ends nobody "typed"
        right = find_add(r["right"]) if t in ("added", "modified") and r.get("right") is not None else None
        left = find_remove(r["left"]) if t in ("removed", "modified") and r.get("left") is not None else None
        if t == "modified" and left is None and right is not None and _same_leaf(r["left"], r["right"]):
            left = right  # typing a new value replaced the old one (description, mtu ...)
        if sole is not None:
            if right is None and t in ("added", "modified"):
                right = _by(sole, "inferred")
            if left is None and t in ("removed", "modified"):
                left = _by(sole, "inferred")
        if right:
            r["right_by"] = right
        if left:
            r["left_by"] = left
        bump(right, "added")
        bump(left, "removed")
    return sorted(counts.values(), key=lambda c: -(c["added"] + c["removed"]))


def commands_summary(edits: list[Edit], limit: int = 200) -> list[dict]:
    return [{"user": e.username, "at": e.at.isoformat(), "command": e.command} for e in edits[-limit:]]
