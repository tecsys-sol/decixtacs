from __future__ import annotations

import os
from pathlib import Path

import pytest

from nom_tacacs_agent.tailer import FileTailer, OffsetStore

L1 = ("2026-09-23 10:01:02 +0000\t10.0.0.1\talice\tssh\t192.0.2.10\tstop\ttask_id=1\tservice=shell"
      "\tcmd=show version <cr>")


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def log(tmp_path):
    p = tmp_path / "acct.log"
    p.write_text("")
    return p


@pytest.fixture
def store(tmp_path):
    return OffsetStore(tmp_path / "state" / "offsets.json")


def test_reads_complete_lines_and_holds_partial(log, store):
    append(log, f"{L1}\nline2\npartial")
    t = FileTailer(log, store)
    assert t.read_lines(10) == [L1, "line2"]
    assert t.read_lines(10) == []
    append(log, " done\n")
    assert t.read_lines(10) == ["partial done"]


def test_batch_limit(log, store):
    append(log, "".join(f"l{i}\n" for i in range(25)))
    t = FileTailer(log, store)
    assert t.read_lines(10) == [f"l{i}" for i in range(10)]
    assert t.read_lines(10) == [f"l{i}" for i in range(10, 20)]
    assert t.read_lines(10) == [f"l{i}" for i in range(20, 25)]


def test_committed_offset_survives_restart(log, store, tmp_path):
    append(log, "a\nb\n")
    t = FileTailer(log, store)
    assert t.read_lines(10) == ["a", "b"]
    t.commit()
    t.close()
    append(log, "c\n")
    t2 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    assert t2.read_lines(10) == ["c"]


def test_uncommitted_lines_are_redelivered(log, store, tmp_path):
    append(log, "a\nb\n")
    t = FileTailer(log, store)
    t.read_lines(1)
    t.commit()  # only "a" acknowledged
    t.read_lines(10)  # "b" read but never acknowledged (crash)
    t2 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    assert t2.read_lines(10) == ["b"]


def test_rename_rotation_drains_old_file_then_follows_new(log, store):
    append(log, "one\ntwo\n")
    t = FileTailer(log, store)
    assert t.read_lines(10) == ["one", "two"]
    # writer still has the old file open and writes one more line after the rename
    rotated = log.with_name("acct.log.1")
    os.rename(log, rotated)
    append(rotated, "three\n")
    log.write_text("four\nfive\n")
    assert t.read_lines(10) == ["three", "four", "five"]
    t.commit()
    append(log, "six\n")
    assert t.read_lines(10) == ["six"]


def test_rotation_with_missing_new_file_keeps_old_handle(log, store):
    append(log, "one\n")
    t = FileTailer(log, store)
    t.read_lines(10)
    os.rename(log, log.with_name("acct.log.1"))
    assert t.read_lines(10) == []  # no new file yet: nothing to do, no crash
    log.write_text("two\n")
    assert t.read_lines(10) == ["two"]


def test_final_unterminated_line_of_rotated_file_is_emitted(log, store):
    append(log, "one\ntwo-without-newline")
    t = FileTailer(log, store)
    assert t.read_lines(10) == ["one"]
    os.rename(log, log.with_name("acct.log.1"))
    log.write_text("three\n")
    assert t.read_lines(10) == ["two-without-newline", "three"]


def test_copytruncate_restarts_from_zero(log, store):
    append(log, "one\ntwo\nthree\n")
    t = FileTailer(log, store)
    assert len(t.read_lines(10)) == 3
    with log.open("r+") as fh:  # logrotate copytruncate
        fh.truncate(0)
    append(log, "four\n")
    assert t.read_lines(10) == ["four"]


def test_rotation_while_agent_was_down(log, store, tmp_path):
    append(log, "one\ntwo\n")
    t = FileTailer(log, store)
    t.read_lines(1)
    t.commit()  # acknowledged "one" only
    t.close()
    append(log, "three\n")
    os.rename(log, log.with_name("acct.log.1"))
    log.write_text("four\n")
    t2 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    assert t2.read_lines(10) == ["two", "three", "four"]
    t2.commit()
    t2.close()
    t3 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    append(log, "five\n")
    assert t3.read_lines(10) == ["five"]


def test_compressed_rotation_is_not_read(log, store, tmp_path):
    append(log, "one\n")
    t = FileTailer(log, store)
    t.read_lines(10)
    t.commit()
    t.close()
    os.rename(log, log.with_name("acct.log.1.gz"))
    log.write_text("two\n")
    t2 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    assert t2.read_lines(10) == ["two"]


def test_offset_beyond_size_after_restart_starts_over(log, store, tmp_path):
    append(log, "one\ntwo\n")
    t = FileTailer(log, store)
    t.read_lines(10)
    t.commit()
    t.close()
    with log.open("r+") as fh:
        fh.truncate(0)
    append(log, "x\n")
    t2 = FileTailer(log, OffsetStore(tmp_path / "state" / "offsets.json"))
    assert t2.read_lines(10) == ["x"]


def test_missing_file_is_picked_up_later(tmp_path, store):
    p = tmp_path / "later.log"
    t = FileTailer(p, store)
    assert t.read_lines(10) == []
    p.write_text("hello\n")
    assert t.read_lines(10) == ["hello"]


def test_start_at_end_skips_history_for_new_files(log, store):
    append(log, "old\n")
    t = FileTailer(log, store, start_at="end")
    assert t.read_lines(10) == []
    append(log, "new\n")
    assert t.read_lines(10) == ["new"]


def test_overlong_line_is_truncated_not_wedged(log, store):
    append(log, "x" * 300 + "\nok\n")
    t = FileTailer(log, store, max_line_bytes=100, chunk_size=64)
    out = t.read_lines(10)
    assert out[-1] == "ok"
    assert "".join(out[:-1]) == "x" * 300


def test_crlf_and_invalid_utf8(log, store):
    with log.open("ab") as fh:
        fh.write(b"win\r\nbad\xff\n")
    t = FileTailer(log, store)
    assert t.read_lines(10) == ["win", "bad�"]


def test_offset_store_is_atomic_json(tmp_path):
    s = OffsetStore(tmp_path / "o.json")
    from nom_tacacs_agent.tailer import Position

    s.set("/a", Position(1, 2, 3))
    assert OffsetStore(tmp_path / "o.json").get("/a") == Position(1, 2, 3)
    (tmp_path / "o.json").write_text("{corrupt")
    assert OffsetStore(tmp_path / "o.json").get("/a") is None
