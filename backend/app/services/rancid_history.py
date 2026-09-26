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
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


def _junos_blocks(body: str) -> list[str]:
    """Split a hierarchical Junos config into its top-level statements (``system { ... }``, ...)."""
    blocks: list[str] = []
    cur: list[str] = []
    depth = 0
    for raw in body.splitlines():
        cur.append(raw)
        line = raw.strip()
        if line == "}":
            depth = max(0, depth - 1)
        elif line.endswith("{") and not line.startswith(("#", "/*")):
            depth += 1
        if depth == 0 and line:
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    return blocks


class JunosCache:
    """Top-level blocks converted to set lines, kept for the next revision: consecutive RANCID
    revisions differ in a few lines, so most blocks are converted once per router."""

    def __init__(self) -> None:
        self.prev: dict[str, list[str]] = {}

    def convert(self, body: str) -> list[str]:
        cur: dict[str, list[str]] = {}
        out: list[str] = []
        for block in _junos_blocks(body):
            lines = cur.get(block) or self.prev.get(block)
            if lines is None:
                lines = rs.junos_to_set(block)
            cur[block] = lines
            out += lines
        self.prev = cur
        return out


def to_nom_format(text: str, platform: str | None, sanitize: bool, cache: JunosCache | None = None) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    if platform == "junos" and not any(ln.startswith("set ") for ln in lines[:300]):
        body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
        content = "\n".join(cache.convert(body) if cache else rs.junos_to_set(body)) + "\n"
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


Progress = Callable[[dict], None]


def import_history(db: Session, tenant_id: uuid.UUID, archive: bytes, progress: Progress | None = None) -> ImportStats:
    """Stream every revision into ``git fast-import``: blobs first, router by router (only one
    revision's text in memory at a time), then the commits in date order referencing them."""
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    slug = tenant.slug
    files = read_rcs_archive(archive)
    del archive
    stats = ImportStats(routers=len(files))
    by_key: dict[str, Device] = {}
    for d in db.scalars(
        select(Device)
        .where(Device.tenant_id == tenant_id)
        .options(selectinload(Device.platform), selectinload(Device.site))
    ):
        for k in (d.hostname.lower(), rs.short(d.hostname), (d.management_ip or "").lower()):
            if k:
                by_key.setdefault(k, d)
    # resolve everything needed from the ORM up front: progress commits expire loaded objects
    targets: list[tuple[str, bytes, str, str | None]] = []  # name, ,v data, repo path, platform
    for name, (_group, raw) in sorted(files.items()):
        d = by_key.get(name.lower()) or by_key.get(rs.short(name))
        if d is None:
            stats.unmatched.append(name)
        else:
            targets.append((name, raw, device_relpath(d), d.platform.slug if d.platform else None))
    files.clear()
    sanitize = sanitize_for(db, tenant_id)

    root = Path(get_settings().backup_repo_root)
    target = root / repo_name(slug)
    tmp = root / f".{repo_name(slug)}.import"
    shutil.rmtree(tmp, ignore_errors=True)
    GitConfigStore(str(root), tmp.name)  # init an empty repository
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv
            [shutil.which("git") or "git", "fast-import", "--quiet", "--force", "--done"],
            cwd=tmp,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
        )
        assert proc.stdin is not None
        out = proc.stdin
        # date, path, blob mark, author, log, rcs revision
        commits: list[tuple[datetime, str, int, str, str, str]] = []
        mark = 0
        try:
            for i, (name, raw, path, plat) in enumerate(targets):
                if progress:
                    progress(
                        {
                            "phase": "revisions",
                            "router": name,
                            "done": i,
                            "total": len(targets),
                            "revisions": stats.revisions,
                        }
                    )
                cache = JunosCache() if plat == "junos" else None
                pending: tuple[str, rcs.Revision] | None = None  # newest kept content, oldest revision with it
                try:
                    for r in rcs.iter_revisions(raw):  # newest first
                        if r.state == "dead" or not r.text.strip():
                            continue
                        stats.revisions += 1
                        content = to_nom_format(r.text, plat, sanitize, cache)
                        if pending is not None and pending[0] == content:
                            # RANCID committed a change NOM's format normalises away (comment
                            # header, volatile line): the config dates from the older revision
                            pending = (content, r)
                            continue
                        if pending is not None:
                            mark += 1
                            out.write(b"blob\nmark :%d\n" % mark + _data(pending[0].encode()))
                            commits.append(_meta(pending[1], path, mark))
                        pending = (content, r)
                except rcs.RcsError as e:
                    stats.errors.append(f"{name}: {e}")
                    continue
                if pending is not None:
                    mark += 1
                    out.write(b"blob\nmark :%d\n" % mark + _data(pending[0].encode()))
                    commits.append(_meta(pending[1], path, mark))
                stats.matched += 1
            if progress:
                progress(
                    {"phase": "commits", "done": len(targets), "total": len(targets), "revisions": stats.revisions}
                )
            commits.sort(key=lambda c: (c[0], c[1]))
            for date, path, blob, author, log, rev in commits:
                ts = int(date.timestamp())
                msg = f"{Path(path).stem}: {log or 'RANCID update'}\n\nSource: RANCID CVS revision {rev}\n"
                who = re.sub(r"[<>\n]", "", author) or "rancid"
                out.write(
                    b"commit refs/heads/main\n"
                    + f"author {who} <{who}@rancid> {ts} +0000\n".encode()
                    + f"committer RANCID import <rancid-import@networkops.local> {ts} +0000\n".encode()
                    + _data(msg.encode())
                    + f"M 100644 :{blob} {path}\n\n".encode()
                )
                stats.commits += 1
                stats.first = stats.first or date
                stats.last = date
            out.write(b"done\n")
            out.close()
            code = proc.wait(timeout=1800)
        except BrokenPipeError:
            proc.wait(timeout=60)
            errors.seek(0)
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"git fast-import stopped: {errors.read().decode(errors='replace')[:500]}") from None
        except BaseException:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if code != 0:
            errors.seek(0)
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"git fast-import failed: {errors.read().decode(errors='replace')[:500]}")
    # swap in as a whole: the previous import is replaced
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return stats


def _meta(r: rcs.Revision, path: str, mark: int) -> tuple[datetime, str, int, str, str, str]:
    return (r.date, path, mark, r.author or "rancid", r.log, r.rev)


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


STALLED_AFTER = timedelta(minutes=10)  # no progress heartbeat for this long: the worker is gone


def is_active(status: dict | None, now: datetime) -> bool:
    """Queued or running, and still reporting progress."""
    if not status or status.get("status") not in ("queued", "running"):
        return False
    beat = status.get("updated_at") or status.get("started_at") or status.get("requested_at")
    try:
        last = datetime.fromisoformat(beat) if beat else None
    except ValueError:
        last = None
    limit = STALLED_AFTER if status.get("status") == "running" else timedelta(hours=1)
    return last is not None and now - last < limit


def run_import(db: Session, tenant_id: uuid.UUID) -> dict:
    """Import the uploaded archive, recording progress in ``Tenant.settings["rancid_history"]``."""
    from app.db.base import utcnow

    path = upload_path(tenant_id)
    now = utcnow().isoformat()
    set_status(db, tenant_id, status="running", started_at=now, updated_at=now, error=None, progress=None)
    db.commit()
    last = [time.monotonic()]

    def progress(p: dict) -> None:
        if time.monotonic() - last[0] < 5 and p.get("phase") == "revisions":
            return
        last[0] = time.monotonic()
        set_status(db, tenant_id, progress=p, updated_at=utcnow().isoformat())
        db.commit()

    try:
        stats = import_history(db, tenant_id, path.read_bytes(), progress)
    except Exception as e:  # noqa: BLE001 - reported to the user, not re-raised into Celery retries
        db.rollback()
        status = set_status(
            db, tenant_id, status="failed", finished_at=utcnow().isoformat(), updated_at=None, error=str(e)[:500]
        )
    else:
        status = set_status(
            db,
            tenant_id,
            status="done",
            finished_at=utcnow().isoformat(),
            updated_at=None,
            progress=None,
            stats=stats.to_dict(),
        )
    path.unlink(missing_ok=True)
    db.commit()
    return status
