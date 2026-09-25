"""Module 4 - Git-backed configuration store (one repository per tenant).

Layout: ``<root>/<tenant-slug>/<site-slug>/<hostname>.cfg``. Every change is a commit whose
author is the engineer correlated from TACACS accounting (or the backup service), with a
structured message::

    MX204-BLR: Added new IX VLAN

    Device: mx204-blr
    Reason: Added new IX VLAN
    Change-Request: CHG-123
    Trigger: schedule
"""

from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from git import Actor, Repo
from git.exc import BadName

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def _lock(path: str):
    """Serialise writers to one repository: a thread lock within the process plus an flock on
    ``.git/nom.lock`` across worker processes/pods sharing the volume."""
    with _locks_guard:
        tlock = _locks.setdefault(path, threading.Lock())
    with tlock:
        os.makedirs(os.path.join(path, ".git"), exist_ok=True)
        with open(os.path.join(path, ".git", "nom.lock"), "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


@dataclass
class CommitInfo:
    sha: str
    author: str
    email: str
    timestamp: datetime
    message: str


class GitConfigStore:
    def __init__(self, root: str, tenant_slug: str):
        self.path = Path(root) / tenant_slug
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            repo = Repo.init(self.path, initial_branch="main")
            with repo.config_writer() as cw:
                cw.set_value("user", "name", "NetworkOps Manager")
                cw.set_value("user", "email", "backup@networkops.local")
                cw.set_value("gc", "auto", "256")
        self.repo = Repo(self.path)

    @staticmethod
    def relpath(site_slug: str | None, hostname: str) -> str:
        safe = hostname.replace("/", "_")
        return f"{site_slug or '_unassigned'}/{safe}.cfg"

    def read(self, relpath: str, rev: str = "HEAD") -> str | None:
        try:
            blob = self.repo.commit(rev).tree / relpath
        except (KeyError, ValueError, BadName):
            return None
        return blob.data_stream.read().decode("utf-8", errors="replace")

    def write(
        self,
        relpath: str,
        content: str,
        *,
        author: str,
        author_email: str | None,
        subject: str,
        trailers: dict[str, str],
        when: datetime | None = None,
    ) -> str | None:
        """Write + commit if content changed. Returns the new commit sha, or None if unchanged."""
        with _lock(str(self.path)):
            full = self.path / relpath
            full.parent.mkdir(parents=True, exist_ok=True)
            if full.exists() and full.read_text(encoding="utf-8", errors="replace") == content:
                return None
            tmp = full.with_suffix(".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, full)
            self.repo.index.add([relpath])
            body = "\n".join(f"{k}: {v}" for k, v in trailers.items() if v)
            actor = Actor(author, author_email or f"{author}@networkops.local")
            committer = Actor("NetworkOps Manager", "backup@networkops.local")
            raw = f"{int(when.timestamp())} +0000" if when else None  # git "raw" date format
            dates = {"author_date": raw, "commit_date": raw} if raw else {}
            commit = self.repo.index.commit(f"{subject}\n\n{body}\n", author=actor, committer=committer, **dates)
            return commit.hexsha

    def delete(self, relpath: str, *, author: str, reason: str) -> str | None:
        with _lock(str(self.path)):
            if not (self.path / relpath).exists():
                return None
            self.repo.index.remove([relpath], working_tree=True)
            commit = self.repo.index.commit(
                f"Remove {relpath}\n\nReason: {reason}\n", author=Actor(author, f"{author}@networkops.local")
            )
            return commit.hexsha

    def last_commit(self, relpath: str) -> str | None:
        try:
            return next(self.repo.iter_commits(paths=relpath, max_count=1)).hexsha
        except (StopIteration, ValueError):
            return None

    def commit_info(self, rev: str) -> CommitInfo | None:
        try:
            c = self.repo.commit(rev)
        except (KeyError, ValueError, BadName):
            return None
        return CommitInfo(c.hexsha, c.author.name or "", c.author.email or "", c.authored_datetime, c.message)

    def history(self, relpath: str, max_count: int = 100) -> list[CommitInfo]:
        out = []
        for c in self.repo.iter_commits(paths=relpath, max_count=max_count):
            out.append(CommitInfo(c.hexsha, c.author.name or "", c.author.email or "", c.authored_datetime, c.message))
        return out
