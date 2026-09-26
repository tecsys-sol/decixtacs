import io
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.services import rcs
from tests.test_api_configs import _backup, _device, fake_collector  # noqa: F401
from tests.test_rancid import JUNOS_HIER

CVS = Path(__file__).parent / "fixtures" / "rancid_cvs"  # built with RCS `ci` (see test below)


def _cvs_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(CVS, arcname=".")
        info = tarfile.TarInfo("./ixp/configs/CVS/Entries")  # CVS bookkeeping is ignored
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    return buf.getvalue()


def test_rcs_rebuilds_every_revision():
    revs = rcs.revisions((CVS / "ixp/configs/mx204-blr,v").read_bytes())
    assert [r.rev for r in revs] == ["1.1", "1.2", "1.3", "1.4"]
    assert revs[0].text == JUNOS_HIER and revs[0].log == "new router" and revs[0].author == "rancid"
    assert revs[0].date == datetime(2019, 3, 1, 10, 0, tzinfo=UTC)
    assert "server 10.0.0.11;" in revs[1].text and "serial changed" in revs[1].text
    assert revs[3].author == "alice" and 'description "noc@de-cix";' in revs[3].text  # "@@" unescaped
    assert revs[3].text.count("\n") == JUNOS_HIER.count("\n") + 1


def test_rcs_apply_reverse_diff():
    newer = ["a\n", "b\n", "c\n", "d\n"]
    assert rcs._apply(newer, "d2 1\na3 2\nx\ny\n") == ["a\n", "c\n", "x\n", "y\n", "d\n"]


def test_import_rancid_history_into_device_history(admin, fake_collector):  # noqa: F811
    dev = _device(admin)
    nom_first = _backup(admin)[0]["commit_sha"]
    assert admin.get("/api/v1/rancid/history").json()["status"] == "none"

    r = admin.post(
        "/api/v1/rancid/history?run_async=false",
        files={"file": ("rancid-cvs.tgz", _cvs_archive(), "application/gzip")},
    )
    assert r.status_code == 202, r.text
    st = r.json()
    assert st["status"] == "done", st
    s = st["stats"]
    # 1.3 only changed RANCID's comment header -> the same config once normalised, not a commit
    assert (s["routers"], s["matched"], s["revisions"], s["commits"]) == (2, 1, 4, 3)
    assert s["unmatched"] == ["old-sw"] and s["first"].startswith("2019-03-01")

    hist = admin.get(f"/api/v1/devices/{dev['id']}/history").json()
    assert [h["source"] for h in hist] == ["nom", "rancid", "rancid", "rancid"]
    assert hist[0]["sha"] == nom_first
    newest, middle, oldest = hist[1], hist[2], hist[3]
    assert newest["author"] == "alice" and "RANCID CVS revision 1.4" in newest["message"]
    assert oldest["timestamp"].startswith("2019-03-01")

    cfg = admin.get(f"/api/v1/devices/{dev['id']}/config", params={"rev": oldest["sha"]}).text
    assert "set system ntp server 10.0.0.10" in cfg and "Chassis" not in cfg and "RANCID" not in cfg

    d = admin.get(f"/api/v1/devices/{dev['id']}/diff", params={"old": middle["sha"], "new": newest["sha"]}).json()
    assert d["added"] == 1 and d["removed"] == 0
    assert any("noc@de-cix" in (row.get("right") or "") for row in d["side_by_side"])
    # across the boundary: the newest RANCID revision vs NOM's first backup
    assert (
        admin.get(f"/api/v1/devices/{dev['id']}/diff", params={"old": newest["sha"], "new": nom_first}).status_code
        == 200
    )

    from app.db.session import SessionLocal
    from app.models import Device
    from app.services import rancid_history
    from app.services.backup.engine import device_relpath

    with SessionLocal() as db:
        device = db.get(Device, uuid.UUID(dev["id"]))
        store = rancid_history.history_store(db, device.tenant_id)
        rows = rancid_history.device_changes(store, device_relpath(device), datetime(2000, 1, 1, tzinfo=UTC))
    assert [(r["author"], r["added"], r["removed"], r["reason"]) for r in rows] == [
        ("alice", 1, 0, "updates"),
        ("rancid", 1, 1, "updates"),
    ]

    # a re-import replaces the previous one; delete removes it and leaves NOM's history alone
    again = admin.post(
        "/api/v1/rancid/history?run_async=false", files={"file": ("x.tgz", _cvs_archive(), "application/gzip")}
    )
    assert again.json()["stats"]["commits"] == 3
    assert len(admin.get(f"/api/v1/devices/{dev['id']}/history").json()) == 4
    assert admin.delete("/api/v1/rancid/history").status_code == 204
    assert [h["sha"] for h in admin.get(f"/api/v1/devices/{dev['id']}/history").json()] == [nom_first]
    assert admin.get("/api/v1/rancid/history").json()["status"] == "none"


def test_import_rejects_archives_without_rcs_files(admin):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("./ixp/configs/router1")
        info.size = 3
        t.addfile(info, io.BytesIO(b"abc"))
    r = admin.post("/api/v1/rancid/history", files={"file": ("x.tgz", buf.getvalue(), "application/gzip")})
    assert r.status_code == 422 and ",v" in r.json()["detail"]


def test_junos_block_cache_matches_full_conversion():
    from app.services import rancid_history as rh

    cache = rh.JunosCache()
    for r in rcs.iter_revisions((CVS / "ixp/configs/mx204-blr,v").read_bytes()):
        assert rh.to_nom_format(r.text, "junos", True, cache) == rh.to_nom_format(r.text, "junos", True)


def test_stalled_import_is_reported_and_can_be_retried(admin, fake_collector):  # noqa: F811
    from datetime import timedelta

    from app.db.session import SessionLocal
    from app.models import Device
    from app.services import rancid_history as rh

    dev = _device(admin)
    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    with SessionLocal() as db:
        tenant_id = db.get(Device, uuid.UUID(dev["id"])).tenant_id
        rh.set_status(db, tenant_id, status="running", requested_at=old, started_at=old, updated_at=old)
        db.commit()
    st = admin.get("/api/v1/rancid/history").json()
    assert st["status"] == "stalled" and "memory" in st["error"]
    r = admin.post(
        "/api/v1/rancid/history?run_async=false", files={"file": ("x.tgz", _cvs_archive(), "application/gzip")}
    )
    assert r.status_code == 202 and r.json()["status"] == "done" and r.json()["progress"] is None

    now = datetime.now(UTC).isoformat()
    with SessionLocal() as db:
        rh.set_status(db, tenant_id, status="running", updated_at=now)
        db.commit()
    assert admin.get("/api/v1/rancid/history").json()["status"] == "running"
    busy = admin.post("/api/v1/rancid/history", files={"file": ("x.tgz", _cvs_archive(), "application/gzip")})
    assert busy.status_code == 409


def test_history_of_a_device_without_nom_backups(admin):
    dev = _device(admin)  # never backed up by NOM: its Git repository has no commit yet
    r = admin.post(
        "/api/v1/rancid/history?run_async=false", files={"file": ("x.tgz", _cvs_archive(), "application/gzip")}
    )
    assert r.json()["status"] == "done"
    hist = admin.get(f"/api/v1/devices/{dev['id']}/history").json()
    assert [h["source"] for h in hist] == ["rancid"] * 3
    cfg = admin.get(f"/api/v1/devices/{dev['id']}/config").text  # HEAD falls back to RANCID's newest
    assert "noc@de-cix" in cfg
