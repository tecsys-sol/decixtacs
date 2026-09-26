"""RANCID migration helpers.

* ``.cloginrc`` -> credentials: the first matching ``add user`` / ``add password`` /
  ``add userpassword`` line per router (Tcl glob patterns, first match wins, as in clogin).
* ``router.db`` -> which inventory devices RANCID backs up, their platform and up/down state.
* RANCID ``configs/`` files -> normalised text to compare with NOM's own backups.
"""

from __future__ import annotations

import fnmatch
import io
import re
import shlex
import tarfile
import zipfile
from dataclasses import dataclass, field

# router.db device type -> NOM platform slug
RANCID_TYPES = {
    "juniper": "junos",
    "junos": "junos",
    "cisco": "ios",
    "ios": "ios",
    "cisco-xe": "ios",
    "cisco-nx": "nxos",
    "nxos": "nxos",
    "arista": "eos",
    "fortigate": "fortios",
    "fortigate-full": "fortios",
    "mikrotik": "routeros",
    "vyos": "vyos",
    "vyatta": "vyos",
}


@dataclass
class Directive:
    kind: str
    pattern: str
    values: list[str]
    line: int


def _tcl_words(text: str) -> list[str]:
    """Split a Tcl-ish line: {braced words}, "quoted words" and bare words."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            out.append(text[i + 1 : j - 1])
            i = j
        elif c == '"':
            j = i + 1
            while j < n and not (text[j] == '"' and text[j - 1] != "\\"):
                j += 1
            out.append(text[i + 1 : j].replace('\\"', '"'))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
    return out


def parse_cloginrc(text: str) -> tuple[list[Directive], list[str]]:
    directives, warnings = [], []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = _tcl_words(line)
        if words[0] == "include":
            warnings.append(f".cloginrc line {no}: 'include {' '.join(words[1:])}' not followed - paste that file too")
            continue
        if words[0] != "add" or len(words) < 3:
            warnings.append(f".cloginrc line {no}: not understood, ignored")
            continue
        directives.append(Directive(words[1].lower(), words[2], words[3:], no))
    return directives, warnings


def lookup(directives: list[Directive], kind: str, names: list[str]) -> Directive | None:
    """First directive of ``kind`` whose glob matches the router name (tried in order of ``names``)."""
    for name in names:
        for d in directives:
            if d.kind == kind and fnmatch.fnmatchcase(name.lower(), d.pattern.lower()):
                return d
    return None


@dataclass
class Login:
    username: str
    password: str | None
    enable: str | None
    identity: str | None = None
    lines: list[int] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.username, self.password, self.enable)


def login_for(directives: list[Directive], names: list[str], default_user: str = "rancid") -> Login | None:
    user = lookup(directives, "user", names)
    pw = lookup(directives, "password", names)
    upw = lookup(directives, "userpassword", names)
    ident = lookup(directives, "identity", names)
    noenable = lookup(directives, "noenable", names)
    autoenable = lookup(directives, "autoenable", names)
    password = (upw.values[0] if upw and upw.values else None) or (pw.values[0] if pw and pw.values else None)
    if password is None and ident is None:
        return None
    enable = pw.values[1] if pw and len(pw.values) > 1 else None
    if enable is not None and (noenable or (autoenable and autoenable.values[:1] == ["1"])):
        enable = None
    return Login(
        username=user.values[0] if user and user.values else default_user,
        password=password,
        enable=enable,
        identity=ident.values[0] if ident and ident.values else None,
        lines=sorted(d.line for d in (user, pw, upw) if d),
    )


@dataclass
class RouterEntry:
    name: str
    type: str
    state: str
    comment: str = ""
    group: str | None = None


def parse_router_db(text: str, group: str | None = None) -> tuple[list[RouterEntry], list[str]]:
    out, warnings = [], []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";") if ";" in line else line.split(":")  # RANCID 3 uses ';', 2.x ':'
        if len(parts) < 3:
            warnings.append(f"router.db line {no}: expected name;type;state")
            continue
        out.append(
            RouterEntry(
                parts[0].strip(), parts[1].strip().lower(), parts[2].strip().lower(), ";".join(parts[3:]), group
            )
        )
    return out, warnings


def short(name: str) -> str:
    return name.lower().split(".")[0]


# --- RANCID config files -------------------------------------------------------------------

_RANCID_COMMENT = re.compile(r"^\s*(!|#)")  # RANCID prefixes the inventory/show output it adds
_BLOCK_OPEN = re.compile(r"^(.*?)\s*\{\s*$")
_LEAF = re.compile(r"^(.*?);\s*(##.*)?$")


def junos_to_set(text: str) -> list[str]:
    """Convert a hierarchical Junos configuration (what RANCID stores) to ``display set`` lines."""
    out: list[str] = []
    bases = [""]  # the enclosing statements joined, one entry per open block
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "/*", "*")):
            continue
        if "/*" in line:
            line = re.sub(r"\s*/\*.*?\*/\s*", " ", line).strip()
        inactive = False
        if line[0] in "ip":
            for prefix in ("inactive: ", "protect: "):
                if line.startswith(prefix):
                    inactive = inactive or prefix == "inactive: "
                    line = line[len(prefix) :]
        if line == "}":
            if len(bases) > 1:
                bases.pop()
            continue
        if line.endswith("{"):
            m = _BLOCK_OPEN.match(line)
            if m:
                bases.append(f"{bases[-1]} {m.group(1)}" if len(bases) > 1 else m.group(1))
                continue
        m = _LEAF.match(line)
        if not m:
            continue
        stmt = m.group(1)
        base = bases[-1]
        bm = re.match(r"^(.*?)\s*\[\s*(.*?)\s*\]$", stmt) if stmt.endswith("]") else None
        values = [f"{bm.group(1)} {v}" for v in shlex.split(bm.group(2), posix=False)] if bm else [stmt]
        for v in values:
            full = f"{base} {v}".strip()
            out.append(f"set {full}")
            if inactive:
                out.append(f"deactivate {full}")
    if "inactive: " not in text:
        return out
    # parent blocks marked inactive
    deact: list[str] = []
    path: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line == "}":
            if path:
                path.pop()
            continue
        inactive = line.startswith("inactive: ")
        line = line.removeprefix("inactive: ").removeprefix("protect: ")
        m = _BLOCK_OPEN.match(line)
        if m:
            path.append(m.group(1))
            if inactive:
                deact.append("deactivate " + " ".join(path))
    return out + deact


def normalise(text: str, platform: str | None) -> list[str]:
    """Comparable lines: drop RANCID's comment header and volatile lines, mask secrets (RANCID and
    NOM may filter them differently); Junos -> sorted set format."""
    from app.services.backup.sanitize import mask_secrets

    lines = [ln.rstrip() for ln in text.splitlines()]
    if platform:
        lines = [mask_secrets(ln, platform) for ln in lines]
    if platform == "junos" or (platform is None and any(ln.rstrip().endswith("{") for ln in lines[:400])):
        if not any(ln.startswith("set ") for ln in lines[:200]):
            body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
            out = junos_to_set(body)
        else:
            out = [ln for ln in lines if ln.startswith(("set ", "deactivate "))]
        return sorted({mask_secrets(ln, "junos") for ln in out})
    volatile = re.compile(
        r"^(Building configuration|Current configuration|! Last configuration change|! NVRAM config|"
        r"ntp clock-period|: Saved|Cryptochecksum)",
        re.I,
    )
    return [ln for ln in lines if ln.strip() and not _RANCID_COMMENT.match(ln) and not volatile.match(ln.strip())]


def read_archive(data: bytes) -> dict[str, tuple[str | None, str]]:
    """{router name: (rancid group, content)} from a .tar(.gz) or .zip of RANCID ``<group>/configs/<name>``
    files (``tar czf rancid.tgz -C /var/lib/rancid .``). Other files are ignored."""
    files: dict[str, tuple[str | None, str]] = {}

    def add(path: str, blob: bytes) -> None:
        parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
        if len(parts) < 2 or parts[-2] != "configs" or parts[-1].startswith(".") or "CVS" in parts:
            return
        if parts[-1].endswith((",v", ".new", ".raw")):
            return
        group = parts[-3] if len(parts) >= 3 else None
        files[parts[-1]] = (group, blob.decode("utf-8", errors="replace"))

    buf = io.BytesIO(data)
    if zipfile.is_zipfile(buf):
        with zipfile.ZipFile(buf) as z:
            for info in z.infolist():
                if not info.is_dir() and info.file_size < 50_000_000:
                    add(info.filename, z.read(info))
        return files
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:*") as t:
        for m in t.getmembers():
            if m.isfile() and m.size < 50_000_000:
                f = t.extractfile(m)
                if f is not None:
                    add(m.name, f.read())
    return files
