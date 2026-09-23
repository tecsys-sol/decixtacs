from __future__ import annotations

import json
import os

from nom_tacacs_agent.api import ApiError
from nom_tacacs_agent.recordings import RecordingUploader, recording_metadata

CAST = '{"version": 2, "width": 80, "height": 24, "timestamp": 1790000000}\n[0.5, "i", "show ver\\r"]\n'


def old(path, age=60):
    t = path.stat().st_mtime - age
    os.utime(path, (t, t))


def test_metadata_from_sidecar_and_filename(tmp_path):
    a = tmp_path / "x.cast"
    a.write_text(CAST)
    (tmp_path / "x.json").write_text(json.dumps({"username": "alice", "device_address": "192.0.2.1",
                                                  "started_at": "2026-09-23T10:00:00Z"}))
    assert recording_metadata(a) == {"username": "alice", "device_address": "192.0.2.1",
                                     "started_at": "2026-09-23T10:00:00Z"}
    b = tmp_path / "bob@2001:db8::1@198.51.100.7@1790000000.cast"
    assert recording_metadata(b) == {"username": "bob", "device_address": "2001:db8::1",
                                     "source_address": "198.51.100.7"}
    assert recording_metadata(tmp_path / "nometa.cast") is None


def test_uploads_settled_files_and_deletes_them(tmp_path, fake_api):
    f = tmp_path / "alice@10.0.0.1@1.cast"
    f.write_text(CAST)
    fresh = tmp_path / "bob@10.0.0.2@2.cast"
    fresh.write_text(CAST)
    old(f)
    up = RecordingUploader(fake_api, tmp_path, settle_seconds=10)
    assert up.scan_once() == (1, 0)
    assert fake_api.uploads == [("alice@10.0.0.1@1.cast", {"username": "alice", "device_address": "10.0.0.1"})]
    assert not f.exists() and fresh.exists()


def test_keep_moves_to_sent(tmp_path, fake_api):
    f = tmp_path / "alice@10.0.0.1@1.cast"
    f.write_text(CAST)
    old(f)
    RecordingUploader(fake_api, tmp_path, settle_seconds=0, keep=True).scan_once()
    assert (tmp_path / "sent" / f.name).exists()


def test_rejected_and_transient_errors(tmp_path, fake_api):
    f = tmp_path / "alice@10.0.0.1@1.cast"
    f.write_text("not a cast")
    old(f)
    fake_api.upload_error = ApiError("not an asciicast v2 file", 422)
    assert RecordingUploader(fake_api, tmp_path, settle_seconds=0).scan_once() == (0, 1)
    assert (tmp_path / "failed" / f.name).exists()
    assert "asciicast" in (tmp_path / "failed" / "alice@10.0.0.1@1.error").read_text()

    g = tmp_path / "bob@10.0.0.2@2.cast"
    g.write_text(CAST)
    old(g)
    fake_api.upload_error = ApiError("down", 503)
    try:
        RecordingUploader(fake_api, tmp_path, settle_seconds=0).scan_once()
        raise AssertionError("expected ApiError")
    except ApiError:
        pass
    assert g.exists()  # retried on the next scan


def test_missing_metadata_goes_to_failed(tmp_path, fake_api):
    f = tmp_path / "anonymous.cast"
    f.write_text(CAST)
    old(f)
    assert RecordingUploader(fake_api, tmp_path, settle_seconds=0).scan_once() == (0, 1)
    assert (tmp_path / "failed" / "anonymous.cast").exists()
