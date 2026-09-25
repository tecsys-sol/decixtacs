from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.models import CommandLog
from app.services import attribution
from app.services import diff as diffsvc
from tests.test_api_configs import CONFIGS, _backup, _device, fake_collector  # noqa: F401

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _log(user, cmd, minute, session="s1"):
    return SimpleNamespace(
        username=user,
        command=cmd,
        timestamp=T0 + timedelta(minutes=minute),
        session_id=session,
        task_id=None,
        port=None,
    )


OLD = """set system host-name mx204-blr
set interfaces xe-0/0/1 description old-peer
set protocols bgp group IX neighbor 10.1.1.1 peer-as 65001
set protocols bgp group IX neighbor 10.1.1.2 peer-as 65002
set snmp community public authorization read-only
"""
NEW = """set system host-name mx204-blr
set interfaces xe-0/0/1 description new-peer
set protocols bgp group IX neighbor 10.1.1.1 peer-as 65001
set protocols bgp group IX neighbor 10.1.1.3 peer-as 65003
set vlans IX-446 vlan-id 446
set snmp community public authorization read-only
"""


def test_junos_attribution_with_edit_paths():
    logs = [
        _log("priya", "show configuration", 0),
        _log("priya", "edit interfaces xe-0/0/1", 1),
        _log("priya", "set description new-peer", 2),
        _log("priya", "top", 3),
        _log("arjun", "delete protocols bgp group IX neighbor 10.1.1.2", 4, "s2"),
        _log("arjun", "set protocols bgp group IX neighbor 10.1.1.3 peer-as 65003", 5, "s2"),
        _log("arjun", "set protocols bgp group IX neighbor 10.1.1.3 peer-as 65003", 5, "s2"),  # start+stop record
        _log("meera", "set vlans IX-446 vlan-id 446 <cr>", 6, "s3"),
    ]
    edits = attribution.expand(logs, junos=True)
    assert [e.full for e in edits][0] == "set interfaces xe-0/0/1 description new-peer"
    assert len(edits) == 4  # show/edit/top dropped, duplicate record collapsed
    rows = diffsvc.side_by_side(OLD, NEW, None)
    authors = attribution.attribute(rows, edits, junos=True)
    by_line = {}
    for r in rows:
        if r.get("right_by"):
            by_line[r["right"]] = r["right_by"]["user"]
        if r.get("left_by"):
            by_line[r["left"]] = r["left_by"]["user"]
    assert by_line["set interfaces xe-0/0/1 description new-peer"] == "priya"
    assert by_line["set interfaces xe-0/0/1 description old-peer"] == "priya"  # replaced leaf value
    assert by_line["set protocols bgp group IX neighbor 10.1.1.2 peer-as 65002"] == "arjun"
    assert by_line["set protocols bgp group IX neighbor 10.1.1.3 peer-as 65003"] == "arjun"
    assert by_line["set vlans IX-446 vlan-id 446"] == "meera"
    assert {a["username"] for a in authors} == {"priya", "arjun", "meera"}
    assert all(r.get("right_by", {}).get("confidence", "exact") == "exact" for r in rows)


def test_line_based_cli_and_inferred_fallback():
    old = "hostname sw1\ninterface Gi0/1\n description old\n shutdown\n"
    new = "hostname sw1\ninterface Gi0/1\n description uplink\nlogging host 10.0.0.9\n"
    logs = [
        _log("shashank", "configure terminal", 0),
        _log("shashank", "interface Gi0/1", 1),
        _log("shashank", "description uplink", 2),
        _log("shashank", "no shutdown", 3),
        _log("shashank", "end", 4),
    ]
    edits = attribution.expand(logs, junos=False)
    assert [e.full for e in edits] == ["interface Gi0/1", "description uplink", "no shutdown"]
    rows = diffsvc.side_by_side(old, new, None)
    attribution.attribute(rows, edits, junos=False)
    changed = [r for r in rows if r["type"] != "equal"]
    assert all(r.get("right_by") or r.get("left_by") for r in changed)
    logging_row = next(r for r in rows if r.get("right") == "logging host 10.0.0.9")
    # nobody typed it, but shashank is the only engineer who configured the device in the window
    assert logging_row["right_by"]["confidence"] == "inferred"
    desc = next(r for r in rows if r.get("right") == " description uplink")
    assert desc["right_by"]["confidence"] == "exact"


def test_two_engineers_leave_unexplained_lines_unattributed():
    rows = diffsvc.side_by_side("a\n", "a\nset x 1\nset y 2\n", None)
    edits = attribution.expand([_log("u1", "set x 1", 0), _log("u2", "set q 9", 1, "s2")], junos=True)
    attribution.attribute(rows, edits, junos=True)
    assert next(r for r in rows if r.get("right") == "set x 1")["right_by"]["user"] == "u1"
    assert "right_by" not in next(r for r in rows if r.get("right") == "set y 2")


def test_diff_endpoint_returns_authors(admin, db, tenant, fake_collector):  # noqa: F811
    dev = _device(admin)
    _backup(admin)
    db.add(
        CommandLog(
            tenant_id=tenant.id,
            username="priya",
            device_id=None,
            device_address="10.0.0.1",
            command="set interfaces ae0 unit 446 vlan-id 446",
            timestamp=datetime.now(UTC),
        )
    )
    db.add(
        CommandLog(
            tenant_id=tenant.id,
            username="priya",
            device_address="10.0.0.1",
            command="delete protocols bgp group TRANSIT neighbor 10.0.0.2",
            timestamp=datetime.now(UTC),
        )
    )
    db.commit()
    fake_collector["version"] = 2
    _backup(admin)
    hist = admin.get(f"/api/v1/devices/{dev['id']}/history").json()
    d = admin.get(f"/api/v1/devices/{dev['id']}/diff", params={"old": hist[1]["sha"], "new": hist[0]["sha"]}).json()
    assert d["attributed"] and d["authors"][0]["username"] == "priya"
    assert d["authors"][0]["added"] == 1 and d["authors"][0]["removed"] == 1
    added = next(r for r in d["side_by_side"] if r.get("right") == "set interfaces ae0 unit 446 vlan-id 446")
    assert added["right_by"]["command"] == "set interfaces ae0 unit 446 vlan-id 446"
    assert len(d["commands"]) == 2
    plain = admin.get(
        f"/api/v1/devices/{dev['id']}/diff", params={"old": hist[1]["sha"], "new": hist[0]["sha"], "attribute": False}
    ).json()
    assert plain["authors"] == [] and not plain["attributed"]
    assert CONFIGS[2]  # fixture data in use
