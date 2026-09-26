"""Import RANCID's CVS history into a per-tenant Git history of its own.

RANCID keeps every router's config in CVS: ``$BASEDIR/CVS/<group>/configs/<router>,v``. Each
revision is rebuilt from the RCS file, converted to the format NOM stores (Junos: ``display set``;
RANCID's comment header dropped; volatile lines and - when the tenant sanitizes - secrets handled
exactly like NOM's own backups) and committed with its original date and log message into
``<repo root>/<tenant>-rancid`` in one ``git fast-import`` run. Device history then shows these
revisions before NOM's own; the newest RANCID revision is the parent of NOM's first backup.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tarfile
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Device, Tenant
from app.services import rancid as rs
from app.services import rcs
from app.services.backup.engine import device_relpath, sanitize_for
from app.services.backup.git_store import GitConfigStore
from app.services.backup.sanitize import prepare

HISTORY_KEY = "rancid_history"  # Tenant.settings: last import status
_INFO_LINE = re.compile(r"^[!#]\s*(RANCID|[A-Za-z][\w /().-]*:)")


def repo_name(tenant_slug: str) -> str:
    return f"{tenant_slug}-rancid"


def history_store(db: Session, tenant_id: uuid.UUID) -> GitConfigStore | None:
    """The tenant's imported RANCID history, if any."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    path = Path(get_settings().backup_repo_root) / repo_name(tenant.slug)
    if not (path / ".git").exists():
        return None
    store = GitConfigStore(get_settings().backup_repo_root, repo_name(tenant.slug))
    try:
        store.repo.head.commit  # noqa: B018 - empty repository check
    except ValueError:
        return None
    return store


def to_nom_format(text: str, platform: str | None, sanitize: bool) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    if platform == "junos" and not any(ln.startswith("set ") for ln in lines[:300]):
        body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
        content = "\n".join(rs.junos_to_set(body)) + "\n"
    else:
        # RANCID prepends inventory / version details as comment lines ("!Chassis type: ...")
        content = "\n".join(ln for ln in lines if not _INFO_LINE.match(ln)) + "\n"
    return prepare(content, platform or "", sanitize)


def read_rcs_archive(data: bytes) -> dict[str, tuple[str | None, bytes]]:
    """{router: (group, ,v bytes)} for ``<group>/configs/[Attic/]<router>,v`` in a .tar(.gz)/.zip."""
    files: dict[str, tuple[str | None, bytes]] = {}

    def add(path: str, blob: bytes) -> None:
        parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or not parts[-1].endswith(",v"):
            return
        if "Attic" in parts:
            parts = [p for p in parts if p != "Attic"]
        if len(parts) < 2 or parts[-2] != "configs":
            return
        name = parts[-1][:-2]
        group = parts[-3] if len(parts) >= 3 else None
        # a live file wins over an Attic (deleted) one of the same name
        if name not in files or "Attic" not in path:
            files[name] = (group, blob)

    buf = io.BytesIO(data)
    if zipfile.is_zipfile(buf):
        with zipfile.ZipFile(buf) as z:
            for info in z.infolist():
                if not info.is_dir():
                    add(info.filename, z.read(info))
        return files
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:*") as t:
        for m in t.getmembers():
            if m.isfile():
                f = t.extractfile(m)
                if f is not None:
                    add(m.name, f.read())
    return files


@dataclass
class ImportStats:
    routers: int = 0
    matched: int = 0
    revisions: int = 0
    commits: int = 0
    unmatched: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "routers": self.routers,
            "matched": self.matched,
            "revisions": self.revisions,
            "commits": self.commits,
            "unmatched": sorted(self.unmatched)[:200],
            "errors": self.errors[:50],
            "first": self.first.isoformat() if self.first else None,
            "last": self.last.isoformat() if self.last else None,
        }


def _data(payload: bytes) -> bytes:
    return b"data %d\n" % len(payload) + payload + b"\n"


def import_history(db: Session, tenant_id: uuid.UUID, archive: bytes) -> ImportStats:
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    files = read_rcs_archive(archive)
    stats = ImportStats(routers=len(files))
    devices = list(
        db.scalars(
            select(Device)
            .where(Device.tenant_id == tenant_id)
            .options(selectinload(Device.platform), selectinload(Device.site))
        )
    )
    by_key: dict[str, Device] = {}
    for d in devices:
        for k in (d.hostname.lower(), rs.short(d.hostname), (d.management_ip or "").lower()):
            if k:
                by_key.setdefault(k, d)
    sanitize = sanitize_for(db, tenant_id)

    entries: list[tuple[datetime, str, str, str, str, str]] = []  # date, path, content, author, log, rev
    for name, (_group, raw) in files.items():
        d = by_key.get(name.lower()) or by_key.get(rs.short(name))
        if d is None:
            stats.unmatched.append(name)
            continue
        try:
            revs = rcs.revisions(raw)
        except rcs.RcsError as e:
            stats.errors.append(f"{name}: {e}")
            continue
        stats.matched += 1
        plat = d.platform.slug if d.platform else None
        path = device_relpath(d)
        for r in revs:
            if r.state == "dead" or not r.text.strip():
                continue
            entries.append((r.date, path, to_nom_format(r.text, plat, sanitize), r.author or "rancid", r.log, r.rev))
    stats.revisions = len(entries)
    entries.sort(key=lambda e: e[0])

    root = Path(get_settings().backup_repo_root)
    target = root / repo_name(tenant.slug)
    tmp = root / f".{repo_name(tenant.slug)}.import"
    shutil.rmtree(tmp, ignore_errors=True)
    GitConfigStore(str(root), tmp.name)  # init an empty repository
    stream = io.BytesIO()
    last_content: dict[str, str] = {}
    for date, path, content, author, log, rev in entries:
        if last_content.get(path) == content:
            continue  # RANCID committed whitespace/comment-only changes we normalise away
        last_content[path] = content
        ts = int(date.timestamp())
        msg = f"{Path(path).stem}: {log or 'RANCID update'}\n\nSource: RANCID CVS revision {rev}\n".encode()
        who = re.sub(r"[<>\n]", "", author) or "rancid"
        stream.write(b"commit refs/heads/main\n")
        stream.write(f"author {who} <{who}@rancid> {ts} +0000\n".encode())
        stream.write(f"committer RANCID import <rancid-import@networkops.local> {ts} +0000\n".encode())
        stream.write(_data(msg))
        stream.write(f"M 100644 inline {path}\n".encode())
        stream.write(_data(content.encode()))
        stats.commits += 1
        stats.first = stats.first or date
        stats.last = date
    if stats.commits:
        proc = subprocess.run(  # noqa: S603 - fixed argv, stream built above
            [shutil.which("git") or "git", "fast-import", "--quiet", "--force"],
            cwd=tmp,
            input=stream.getvalue(),
            capture_output=True,
            timeout=1800,
        )
        if proc.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"git fast-import failed: {proc.stderr.decode(errors='replace')[:500]}")
    # swap in atomically-ish: the previous import is replaced as a whole
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return stats


def device_changes(store: GitConfigStore, path: str, since: datetime, limit: int = 2000) -> list[dict]:
    """RANCID revisions of one device since ``since`` as change rows (newest first); the device's
    oldest imported revision is its whole config, not a change."""
    from app.services import diff as diffsvc

    commits = store.history(path, limit)
    out = []
    for i, c in enumerate(commits):
        if c.timestamp < since or i + 1 >= len(commits):
            break
        new, old = store.read(path, c.sha) or "", store.read(path, commits[i + 1].sha) or ""
        st = diffsvc.stats(old, new)
        subject = c.message.split("\n", 1)[0]
        out.append(
            {
                "id": c.sha,
                "at": c.timestamp,
                "commit": c.sha,
                "author": c.author or None,
                "reason": subject.split(": ", 1)[-1],
                "added": st.added,
                "removed": st.removed,
                "risk": None,
                "trigger": "rancid",
                "change_request_id": None,
                "source": "rancid",
            }
        )
    return out


def upload_path(tenant_id: uuid.UUID) -> Path:
    """Where an uploaded CVS archive waits for the worker (on the volume API and worker share)."""
    return Path(get_settings().backup_repo_root) / ".imports" / f"{tenant_id}-rancid-cvs"


def set_status(db: Session, tenant_id: uuid.UUID, **values) -> dict:
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    settings = dict(tenant.settings or {})  # new dict so the JSON column change is detected
    status = {**(settings.get(HISTORY_KEY) or {}), **values}
    settings[HISTORY_KEY] = status
    tenant.settings = settings
    return status


def run_import(db: Session, tenant_id: uuid.UUID) -> dict:
    """Import the uploaded archive, recording progress in ``Tenant.settings["rancid_history"]``."""
    from app.db.base import utcnow

    path = upload_path(tenant_id)
    set_status(db, tenant_id, status="running", started_at=utcnow().isoformat(), error=None)
    db.commit()
    try:
        stats = import_history(db, tenant_id, path.read_bytes())
    except Exception as e:  # noqa: BLE001 - reported to the user, not re-raised into Celery retries
        status = set_status(db, tenant_id, status="failed", finished_at=utcnow().isoformat(), error=str(e)[:500])
    else:
        status = set_status(db, tenant_id, status="done", finished_at=utcnow().isoformat(), stats=stats.to_dict())
    path.unlink(missing_ok=True)
    db.commit()
    return status
