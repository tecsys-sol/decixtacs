"""Read RCS ``,v`` files (the storage format behind CVS, which RANCID uses by default).

An RCS file holds the newest trunk revision in full and every older revision as a reverse diff
(``dL N`` delete N lines from line L, ``aL N`` add the next N lines after line L, both counted
in the newer text). ``revisions()`` rebuilds every trunk revision, oldest first.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

_REV = re.compile(r"^\d+(\.\d+)+$")


class RcsError(ValueError):
    pass


@dataclass
class Revision:
    rev: str
    date: datetime
    author: str
    state: str
    log: str
    text: str


def _tokens(data: str):
    """Yield ('s', string) for @...@ strings, ('w', word) and (';', ';')."""
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c.isspace():
            i += 1
        elif c == ";":
            yield (";", ";")
            i += 1
        elif c == "@":
            j = i + 1
            parts = []
            while True:
                k = data.find("@", j)
                if k < 0:
                    raise RcsError("unterminated @string@")
                if k + 1 < n and data[k + 1] == "@":
                    parts.append(data[j : k + 1])  # "@@" -> "@"
                    j = k + 2
                    continue
                parts.append(data[j:k])
                i = k + 1
                break
            yield ("s", "".join(parts))
        elif c == ":":
            yield ("w", ":")
            i += 1
        else:
            j = i
            while j < n and not data[j].isspace() and data[j] not in ";@:":
                j += 1
            yield ("w", data[i:j])
            i = j


def _date(value: str) -> datetime:
    parts = [int(p) for p in value.split(".")]
    if len(parts) != 6:
        raise RcsError(f"bad date {value!r}")
    if parts[0] < 100:  # RCS used two-digit years before 2000
        parts[0] += 1900
    return datetime(*parts, tzinfo=UTC)


def _apply(newer: list[str], script: str) -> list[str]:
    """Apply a reverse diff to the newer revision's lines to get the older one."""
    out: list[str] = []
    pos = 0  # lines of `newer` consumed
    lines = script.splitlines(keepends=True)
    k = 0
    while k < len(lines):
        cmd = lines[k].strip()
        k += 1
        if not cmd:
            continue
        m = re.match(r"^([ad])(\d+) (\d+)$", cmd)
        if not m:
            raise RcsError(f"bad edit command {cmd!r}")
        op, line, count = m.group(1), int(m.group(2)), int(m.group(3))
        if op == "d":
            start = line - 1
            if start < pos:
                raise RcsError("overlapping delete")
            out.extend(newer[pos:start])
            pos = start + count
        else:
            if line < pos:
                raise RcsError("add before current position")
            out.extend(newer[pos:line])
            pos = line
            out.extend(lines[k : k + count])
            k += count
    out.extend(newer[pos:])
    return out


def revisions(data: str | bytes) -> list[Revision]:
    """All trunk revisions of an RCS file, oldest first."""
    out = list(iter_revisions(data))
    out.reverse()
    return out


def iter_revisions(data: str | bytes) -> Iterator[Revision]:
    """Trunk revisions newest first, rebuilt one at a time (only the current text is held)."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    toks = list(_tokens(data))
    i = 0
    head = None
    meta: dict[str, dict] = {}

    def value_until_semicolon(start: int) -> tuple[list[str], int]:
        vals = []
        while start < len(toks) and toks[start][0] != ";":
            vals.append(toks[start][1])
            start += 1
        return vals, start + 1

    # admin + delta sections, up to "desc"
    while i < len(toks):
        kind, val = toks[i]
        if kind == "w" and val == "head":
            vals, i = value_until_semicolon(i + 1)
            head = vals[0] if vals else None
            continue
        if kind == "w" and val == "desc":
            i += 2  # desc @...@
            break
        if kind == "w" and _REV.match(val) and i + 1 < len(toks) and toks[i + 1] == ("w", "date"):
            rev = val
            info: dict = {"next": None, "author": "", "state": "", "date": None}
            i += 1
            while i < len(toks):
                k2, v2 = toks[i]
                if k2 == "w" and v2 in ("date", "author", "state", "next", "branches", "commitid"):
                    vals, i = value_until_semicolon(i + 1)
                    if v2 == "date":
                        info["date"] = _date(vals[0])
                    elif v2 == "next":
                        info["next"] = vals[0] if vals else None
                    elif v2 in ("author", "state"):
                        info[v2] = vals[0] if vals else ""
                    continue
                break
            meta[rev] = info
            continue
        i += 1
    if head is None:
        raise RcsError("no head revision")

    # deltatext
    texts: dict[str, tuple[str, str]] = {}
    while i < len(toks):
        kind, val = toks[i]
        if kind == "w" and _REV.match(val):
            rev = val
            log = text = ""
            i += 1
            while i < len(toks):
                k2, v2 = toks[i]
                if k2 == "w" and v2 == "log" and i + 1 < len(toks) and toks[i + 1][0] == "s":
                    log = toks[i + 1][1]
                    i += 2
                elif k2 == "w" and v2 == "text" and i + 1 < len(toks) and toks[i + 1][0] == "s":
                    text = toks[i + 1][1]
                    i += 2
                    break
                else:
                    i += 1
            texts[rev] = (log, text)
            continue
        i += 1

    # walk the trunk from head backwards
    rev: str | None = head
    lines: list[str] | None = None
    seen = set()
    while rev and rev in meta and rev not in seen:
        seen.add(rev)
        log, text = texts.get(rev, ("", ""))
        lines = text.splitlines(keepends=True) if lines is None else _apply(lines, text)
        info = meta[rev]
        yield Revision(rev, info["date"], info["author"], info["state"], log.strip(), "".join(lines))
        texts.pop(rev, None)
        rev = info["next"]
