"""Follow tac_plus-ng log files with durable offsets and log-rotation handling.

Semantics are *at-least-once*: ``read_lines`` advances an in-memory position, ``commit`` persists
it after the platform acknowledged the batch. After a crash the agent re-reads from the last
committed offset, so a batch may be ingested twice but is never lost.

Rotation handling:

* **rename + create** (logrotate default, ``tac_plus-ng`` reopening its log): the tailer keeps the
  old file handle open, drains it to EOF, then switches to the new file at offset 0.
* **copytruncate**: the file shrinks below our position -> restart from 0.
* **rotated while the agent was down**: the stored (device, inode) no longer matches the live file;
  the tailer looks for a sibling (``acct.log.1``, ``acct.log-20260923`` ...) with that inode, drains
  it from the stored offset, then continues with the live file. Compressed rotations cannot be
  read - use logrotate ``delaycompress``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)


@dataclass
class Position:
    dev: int
    ino: int
    offset: int


class OffsetStore:
    """Tiny JSON offset database (atomic replace + fsync), shared by all tailers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, int]] = {}
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            log.warning("offset store %s unreadable (%s); starting fresh", self.path, exc)

    def get(self, key: str) -> Position | None:
        with self._lock:
            d = self._data.get(key)
        if not d:
            return None
        return Position(int(d["dev"]), int(d["ino"]), int(d["offset"]))

    def set(self, key: str, pos: Position) -> None:
        with self._lock:
            self._data[key] = {"dev": pos.dev, "ino": pos.ino, "offset": pos.offset}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)


class FileTailer:
    def __init__(self, path: str | Path, store: OffsetStore, *, start_at: str = "beginning",
                 max_line_bytes: int = 65536, chunk_size: int = 65536):
        self.path = Path(path)
        self.key = str(self.path)
        self.store = store
        self.start_at = start_at
        self.max_line_bytes = max_line_bytes
        self.chunk_size = chunk_size
        self._fh: BinaryIO | None = None
        self._ident: tuple[int, int] | None = None  # (dev, ino) of the open file
        self._pos = 0  # offset just after the last consumed complete line
        self._buf = b""  # bytes read past _pos that do not form a complete line yet
        self._draining_rotated = False

    # --- opening ---------------------------------------------------------------------------

    def _open(self) -> bool:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return False
        saved = self.store.get(self.key)
        if saved and (saved.dev, saved.ino) == (st.st_dev, st.st_ino):
            offset = saved.offset if saved.offset <= st.st_size else 0
            return self._open_file(self.path, offset, st)
        if saved:
            rotated = self._find_rotated(saved)
            if rotated is not None:
                path, rst = rotated
                log.info("%s rotated while stopped; draining %s from offset %d", self.path, path, saved.offset)
                self._draining_rotated = True
                return self._open_file(path, min(saved.offset, rst.st_size), rst)
            log.warning("%s: saved inode not found (rotated and compressed/removed?); starting at 0", self.path)
            return self._open_file(self.path, 0, st)
        return self._open_file(self.path, st.st_size if self.start_at == "end" else 0, st)

    def _find_rotated(self, saved: Position) -> tuple[Path, os.stat_result] | None:
        parent = self.path.parent
        try:
            names = sorted(os.listdir(parent))
        except OSError:
            return None
        for name in names:
            if not name.startswith(self.path.name) or name == self.path.name:
                continue
            if name.endswith((".gz", ".xz", ".bz2", ".zst")):
                continue
            p = parent / name
            try:
                st = os.stat(p)
            except OSError:
                continue
            if (st.st_dev, st.st_ino) == (saved.dev, saved.ino):
                return p, st
        return None

    def _open_file(self, path: Path, offset: int, st: os.stat_result) -> bool:
        try:
            fh = open(path, "rb")  # noqa: SIM115 - long-lived handle
        except OSError as exc:
            log.warning("cannot open %s: %s", path, exc)
            return False
        # guard against the path being swapped between stat and open
        fst = os.fstat(fh.fileno())
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            fh.close()
            return False
        fh.seek(offset)
        self._fh, self._ident, self._pos, self._buf = fh, (st.st_dev, st.st_ino), offset, b""
        return True

    def close(self) -> None:
        if self._fh:
            self._fh.close()
        self._fh = None

    # --- reading ---------------------------------------------------------------------------

    def _read_from_handle(self, want: int, out: list[str]) -> bool:
        """Read complete lines into ``out``; returns True when EOF of the handle was reached."""
        assert self._fh is not None
        while len(out) < want:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                self._pos += nl + 1
                out.append(line.rstrip(b"\r").decode("utf-8", errors="replace"))
                continue
            if len(self._buf) >= self.max_line_bytes:
                # pathological line without newline: emit a truncated record rather than wedge
                out.append(self._buf.decode("utf-8", errors="replace"))
                self._pos += len(self._buf)
                self._buf = b""
                continue
            chunk = self._fh.read(self.chunk_size)
            if not chunk:
                return True
            self._buf += chunk
        return False

    def read_lines(self, max_lines: int = 500) -> list[str]:
        out: list[str] = []
        if self._fh is None and not self._open():
            return out
        for _ in range(4):  # bounded: at most a couple of rotations per call
            at_eof = self._read_from_handle(max_lines, out)
            if not at_eof:
                return out
            if not self._check_rotation(out):
                return out
        return out

    def _check_rotation(self, out: list[str]) -> bool:
        """At EOF: detect rename/truncate. Returns True if a new file was opened (keep reading)."""
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return False  # rotated, new file not created yet: keep the old handle
        assert self._ident is not None
        if (st.st_dev, st.st_ino) != self._ident:
            if self._buf:
                # the writer is gone from the old file; its last line had no newline
                out.append(self._buf.decode("utf-8", errors="replace"))
                self._pos += len(self._buf)
                self._buf = b""
            log.info("%s: rotation detected, switching to new file", self.path)
            self.close()
            self._draining_rotated = False
            return self._open_file(self.path, 0, st)
        if st.st_size < self._pos:
            log.info("%s: truncated (copytruncate), restarting at 0", self.path)
            assert self._fh is not None
            self._fh.seek(0)
            self._pos, self._buf = 0, b""
            return True
        return False

    def commit(self) -> None:
        """Persist the position of everything returned by ``read_lines`` so far."""
        if self._ident is None:
            return
        self.store.set(self.key, Position(self._ident[0], self._ident[1], self._pos))

    @property
    def position(self) -> tuple[tuple[int, int] | None, int]:
        return self._ident, self._pos
