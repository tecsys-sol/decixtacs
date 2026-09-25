import io
import json
import os
import time
from datetime import UTC, datetime

import httpx
import respx
from openpyxl import load_workbook
from sqlalchemy import text

from app.db.session import engine
from tests.test_api_tacacs import as_agent

NB = "https://netbox.example.net"


def _nb_page(results):
    return httpx.Response(200, json={"count": len(results), "next": None, "results": results})


@respx.mock
def test_netbox_sync(admin):
    respx.get(f"{NB}/api/dcim/sites/").mock(
        return_value=_nb_page([{"id": 1, "name": "Bangalore", "slug": "blr", "latitude": 12.9, "longitude": 77.6}])
    )
    long_rack = "Rack " + "x" * 95  # NetBox allows 100 characters
    respx.get(f"{NB}/api/dcim/racks/").mock(
        return_value=_nb_page(
            [
                {"id": 5, "name": "R01", "site": {"id": 1}, "u_height": 42},
                {"id": 6, "name": long_rack, "site": {"id": 1}},
            ]
        )
    )
    devices = [
        {
            "id": 10,
            "name": "mx204-blr",
            "primary_ip4": {"address": "10.0.0.1/32"},
            "site": {"id": 1},
            "rack": {"id": 5},
            "device_type": {"model": "MX204", "manufacturer": {"slug": "juniper", "name": "Juniper"}},
            "platform": {"slug": "juniper-junos", "name": "Junos"},
            "serial": "ABC123",
            "role": {"slug": "core"},
            "status": {"value": "active"},
            "tags": [{"slug": "ixp"}],
            "custom_fields": {},
        },
        {"id": 11, "name": "no-ip-device", "primary_ip4": None, "site": {"id": 1}},
        {
            "id": 12,
            "name": "eos-sw1",
            "primary_ip4": {"address": "10.0.0.2/32"},
            "site": {"id": 1},
            "device_type": {"model": "7280R3", "manufacturer": {"slug": "arista", "name": "Arista"}},
            "platform": {"slug": "arista-eos"},
            "status": {"value": "active"},
            "tags": [],
        },
    ]
    respx.get(f"{NB}/api/dcim/devices/").mock(return_value=_nb_page(devices))
    respx.get(f"{NB}/api/dcim/cables/").mock(
        return_value=_nb_page(
            [
                {
                    "status": {"value": "connected"},
                    "a_terminations": [{"object": {"name": "et-0/0/0", "device": {"name": "mx204-blr"}}}],
                    "b_terminations": [{"object": {"name": "Ethernet1", "device": {"name": "eos-sw1"}}}],
                }
            ]
        )
    )
    vlans = respx.get(f"{NB}/api/ipam/vlans/").mock(
        return_value=_nb_page(
            [
                {"id": 446, "display": "IX-LAN (446)", "vid": 446, "name": "IX-LAN", "site": {"name": "Bangalore"}},
                {"id": 447, "display": "OLD (447)", "vid": 447, "name": "OLD"},
            ]
        )
    )
    respx.get(f"{NB}/api/ipam/prefixes/").mock(
        return_value=_nb_page(
            [
                {
                    "id": 1,
                    "prefix": "185.1.0.0/24",
                    "status": {"value": "active"},
                    "vlan": {"id": 446, "vid": 446, "name": "IX-LAN"},
                    "scope_type": "dcim.site",
                    "scope": {"id": 1, "name": "Bangalore"},
                    "vrf": None,
                    "url": f"{NB}/api/ipam/prefixes/1/",
                },
                {"id": 2, "prefix": "2001:7f8:1::/64", "status": {"value": "active"}, "vlan": {"id": 446, "vid": 446}},
                {"id": 3, "prefix": "10.0.0.0/24", "status": {"value": "reserved"}, "vrf": {"name": "MGMT"}},
            ]
        )
    )
    respx.get(f"{NB}/api/ipam/ip-addresses/").mock(
        return_value=_nb_page(
            [
                {
                    "id": 7,
                    "address": "10.0.0.1/32",
                    "status": {"value": "active"},
                    "vrf": {"name": "MGMT"},
                    "dns_name": "mx204-blr.mgmt",
                    "assigned_object": {"name": "fxp0", "device": {"name": "mx204-blr"}},
                },
                {"id": 8, "address": "185.1.0.10/24", "status": {"value": "active"}},
            ]
        )
    )
    respx.get(f"{NB}/api/ipam/vrfs/").mock(return_value=_nb_page([{"id": 1, "name": "MGMT", "rd": "65000:1"}]))
    respx.get(f"{NB}/api/ipam/asns/").mock(return_value=_nb_page([]))
    respx.get(f"{NB}/api/tenancy/contacts/").mock(return_value=_nb_page([]))

    i = admin.post("/api/v1/integrations", json={"kind": "netbox", "name": "nb", "base_url": NB, "token": "t0k"}).json()
    stats = admin.post(f"/api/v1/integrations/{i['id']}/sync", params={"run_async": False}).json()
    assert stats["devices"] == 3 and stats["links"] == 1 and stats["vlan"] == 2 and stats["racks"] == 2
    assert stats["devices_without_ip"] == 1 and stats["devices_without_ip_examples"] == ["no-ip-device"]
    devs = {d["hostname"]: d for d in admin.get("/api/v1/devices").json()["items"]}
    assert devs["mx204-blr"]["platform"]["slug"] == "junos" and devs["eos-sw1"]["platform"]["slug"] == "eos"
    assert devs["mx204-blr"]["serial"] == "ABC123" and devs["mx204-blr"]["site"]["name"] == "Bangalore"
    assert devs["no-ip-device"]["management_ip"] == "" and devs["no-ip-device"]["backup_enabled"] is False
    topo = admin.get("/api/v1/topology").json()
    assert len(topo["nodes"]) == 3 and topo["edges"][0]["label"] == "et-0/0/0 - Ethernet1"
    assert admin.get("/api/v1/external-objects", params={"object_type": "vlan"}).json()[0]["display"] == "IX-LAN (446)"
    # IPAM views
    summ = admin.get("/api/v1/ipam/summary").json()
    assert summ["counts"] == {"prefixes": 3, "vlans": 2, "ip-addresses": 2, "vrfs": 1}
    assert summ["prefix_status"] == {"active": 2, "reserved": 1} and summ["prefix_family"] == {"IPv4": 2, "IPv6": 1}
    pfx = admin.get("/api/v1/ipam/prefixes").json()
    assert [p["prefix"] for p in pfx["items"]] == ["185.1.0.0/24", "2001:7f8:1::/64", "10.0.0.0/24"]
    assert pfx["items"][0]["site"] == "Bangalore" and pfx["items"][0]["url"] == f"{NB}/ipam/prefixes/1/"
    assert admin.get("/api/v1/ipam/prefixes", params={"vrf": "MGMT"}).json()["total"] == 1
    assert admin.get("/api/v1/ipam/prefixes", params={"family": 6}).json()["total"] == 1
    v = admin.get("/api/v1/ipam/vlans", params={"q": "ix-lan"}).json()["items"]
    assert v[0]["prefixes"] == ["185.1.0.0/24", "2001:7f8:1::/64"]
    ips = admin.get("/api/v1/ipam/ip-addresses", params={"device": "mx204-blr"}).json()["items"]
    assert ips[0]["interface"] == "fxp0" and ips[0]["device_id"] == devs["mx204-blr"]["id"]
    assert admin.get("/api/v1/ipam/ip-addresses", params={"within": "185.1.0.0/24"}).json()["total"] == 1
    assert admin.get("/api/v1/ipam/vrfs").json()["items"][0]["prefixes"] == 1
    assert admin.get("/api/v1/ipam/nope").status_code == 404
    assert admin.get("/api/v1/ipam/prefixes", params={"within": "x"}).status_code == 422
    # idempotent; objects deleted in NetBox disappear
    vlans.mock(return_value=_nb_page([{"id": 446, "display": "IX-LAN (446)", "vid": 446, "name": "IX-LAN"}]))
    again = admin.post(f"/api/v1/integrations/{i['id']}/sync", params={"run_async": False}).json()
    assert again["vlan"] == 1 and again["vlan_removed"] == 1
    assert admin.get("/api/v1/devices").json()["total"] == 3
    # auth header sent
    assert respx.calls[0].request.headers["Authorization"] == "Token t0k"


@respx.mock
def test_ixpmanager_and_birdseye(admin):
    ixp_url, rs_url = "https://ixp.example.net", "https://rs1.example.net"
    respx.get(f"{ixp_url}/api/v4/member-export/ixf/1.0").mock(
        return_value=httpx.Response(
            200,
            json={
                "ixp_list": [{"switch": [{"id": 1, "name": "sw1-blr"}], "vlan": [{"id": 1, "name": "Peering LAN"}]}],
                "member_list": [
                    {
                        "asnum": 13335,
                        "name": "Cloudflare",
                        "peering_policy": "open",
                        "member_type": "peering",
                        "connection_list": [
                            {
                                "state": "active",
                                "if_list": [{"switch_id": 1, "if_speed": 100000}],
                                "vlan_list": [
                                    {
                                        "vlan_id": 1,
                                        "ipv4": {
                                            "address": "185.1.1.10",
                                            "routeserver": True,
                                            "as_macro": "AS-CLOUDFLARE",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )
    )
    respx.get(f"{rs_url}/api/protocols/bgp").mock(
        return_value=httpx.Response(
            200,
            json={
                "protocols": {
                    "pb_0001_as13335": {
                        "neighbor_address": "185.1.1.10",
                        "neighbor_as": 13335,
                        "state": "up",
                        "routes": {"imported": 1200, "filtered": 3, "exported": 90000},
                    }
                }
            },
        )
    )
    respx.get(f"{rs_url}/api/routes/filtered/pb_0001_as13335").mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {"bgp": {"large_communities": [[65000, 1101, 9]]}},
                    {"bgp": {"large_communities": [[65000, 1101, 12]]}},
                    {"bgp": {"large_communities": [[65000, 1000, 1]]}},
                ]
            },
        )
    )
    ixp = admin.post(
        "/api/v1/integrations", json={"kind": "ixpmanager", "name": "ixpm", "base_url": ixp_url, "token": "k"}
    ).json()
    rs = admin.post(
        "/api/v1/integrations",
        json={
            "kind": "birdseye",
            "name": "rs1-v4",
            "base_url": rs_url,
            "options": {"rs_asn": 65000, "filter_reasons": True},
        },
    ).json()
    assert admin.post(f"/api/v1/integrations/{ixp['id']}/sync", params={"run_async": False}).json() == {"members": 1}
    admin.post(f"/api/v1/integrations/{rs['id']}/sync", params={"run_async": False})
    m = admin.get("/api/v1/ixp/members").json()[0]
    assert m["asn"] == 13335 and m["connections"][0]["ports"][0]["switch"] == "sw1-blr"
    assert m["connections"][0]["vlans"][0]["rs_client_v4"] is True
    c = admin.get("/api/v1/ixp/route-server-clients", params={"only_problems": True}).json()[0]
    assert c["member"] == "Cloudflare" and c["accepted"] == 1200 and c["filtered"] == 3
    assert c["irr_filtered"] == 1 and c["rpki_invalid"] == 1 and c["irr_status"] == "filtered"
    assert [s["type"] for s in admin.get("/api/v1/search", params={"q": "AS13335"}).json()] == ["ixp_member"]
    assert respx.calls[0].request.headers["X-IXP-Manager-API-Key"] == "k"


@respx.mock
def test_failed_sync_marks_integration_and_alerts(admin):
    respx.get("https://nb.bad/api/dcim/sites/").mock(return_value=httpx.Response(500))
    i = admin.post(
        "/api/v1/integrations", json={"kind": "netbox", "name": "bad", "base_url": "https://nb.bad", "token": "x"}
    ).json()
    try:
        admin.post(f"/api/v1/integrations/{i['id']}/sync", params={"run_async": False})
    except httpx.HTTPStatusError:
        pass
    got = admin.get("/api/v1/integrations").json()[0]
    assert got["last_sync_status"] == "failed"
    assert admin.get("/api/v1/alerts", params={"event_type": "sync_failed"}).json()["total"] == 1


def test_reports_all_formats(admin):
    admin.post("/api/v1/devices", json={"hostname": "r1", "management_ip": "10.0.0.1"})
    for rt in ("device_changes", "config_changes", "user_activity", "compliance", "tacacs"):
        r = admin.get(f"/api/v1/reports/{rt}", params={"period": "weekly"})
        assert r.status_code == 200 and r.json()["columns"]
    ua = admin.get("/api/v1/reports/user_activity").json()
    assert ["admin", 1, 0, 0] == ua["rows"][0][:4]
    csv = admin.get("/api/v1/reports/user_activity", params={"fmt": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.startswith("User,")
    xlsx = admin.get("/api/v1/reports/user_activity", params={"fmt": "xlsx"})
    assert load_workbook(io.BytesIO(xlsx.content)).active["A4"].value == "User"
    pdf = admin.get("/api/v1/reports/tacacs", params={"fmt": "pdf", "period": "monthly"})
    assert pdf.content.startswith(b"%PDF")
    assert admin.get("/api/v1/reports/nope").status_code == 422


def test_session_recording_upload_and_replay(admin):
    srv = admin.post("/api/v1/tacacs/servers", json={"name": "tac1", "address": "10.0.0.5"}).json()
    admin.post("/api/v1/devices", json={"hostname": "mx204-blr", "management_ip": "10.0.0.1"})
    cast = (
        "\n".join(
            [
                json.dumps({"version": 2, "width": 120, "height": 40, "timestamp": 1790000000}),
                json.dumps([0.5, "o", "mx204-blr> "]),
                json.dumps([1.0, "i", "show bgp summ"]),
                json.dumps([1.1, "i", "\x7fmary\r"]),
                json.dumps([2.0, "o", "Groups: 3"]),
                json.dumps([3.0, "i", "exit\r"]),
            ]
        )
        + "\n"
    )
    agent = as_agent(admin, srv["agent_token"])
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Kolkata"  # API process zone != database session zone (UTC)
    time.tzset()
    try:
        r = agent.post(
            "/api/v1/sessions",
            files={"file": ("s.cast", cast.encode(), "application/x-asciicast")},
            data={"username": "shashank", "device_address": "10.0.0.1"},
        )
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
    assert r.status_code == 201, r.text
    rec = r.json()
    assert [c["cmd"] for c in rec["commands"]] == ["show bgp summary", "exit"] and rec["device_id"]
    # the header epoch is stored as that instant, whatever the API process' local time zone is
    assert datetime.fromisoformat(rec["started_at"]) == datetime.fromtimestamp(1790000000, UTC)
    assert admin.get("/api/v1/sessions", params={"command": "bgp"}).json()["total"] == 1
    replay = admin.get(f"/api/v1/sessions/{rec['id']}/cast")
    assert replay.status_code == 200 and replay.text == cast
    assert admin.get("/api/v1/audit", params={"action": "session.replay"}).json()["total"] == 1
    bad = agent.post(
        "/api/v1/sessions",
        files={"file": ("x", b"nope", "text/plain")},
        data={"username": "x", "device_address": "1.1.1.1"},
    )
    assert bad.status_code == 422


def test_audit_append_only_and_tamper_detection(admin):
    admin.post("/api/v1/devices", json={"hostname": "r1", "management_ip": "10.0.0.1"})
    assert admin.get("/api/v1/audit/verify").json()["intact"]
    import pytest
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(text("UPDATE audit_events SET actor_name = 'mallory'"))
    with engine.begin() as c:  # a DBA bypassing the guard is still caught by the hash chain
        c.execute(text("SET LOCAL nom.allow_audit_purge = 'on'"))
        c.execute(text("UPDATE audit_events SET actor_name = 'mallory' WHERE action = 'device.create'"))
    assert admin.get("/api/v1/audit/verify").json()["intact"] is False


def test_partition_helpers():
    with engine.begin() as c:
        parts = c.execute(
            text(
                "SELECT count(*) FROM pg_inherits i JOIN pg_class p ON p.oid=i.inhparent WHERE p.relname='command_logs'"
            )
        ).scalar()
        assert parts >= 5  # last month .. +3 months + default
        c.execute(
            text(
                "CREATE TABLE command_logs_y2001m01 PARTITION OF command_logs "
                "FOR VALUES FROM ('2001-01-01') TO ('2001-02-01')"
            )
        )
        assert c.execute(text("SELECT nom_drop_old_partitions('command_logs', 365)")).scalar() == 1
        assert c.execute(text("SELECT to_regclass('command_logs_y2001m01')")).scalar() is None


def test_alert_channel_delivery(admin):
    with respx.mock:
        hook = respx.post("https://hooks.slack.test/x").mock(return_value=httpx.Response(200))
        ch = admin.post(
            "/api/v1/alerts/channels", json={"name": "noc", "kind": "slack", "target": "https://hooks.slack.test/x"}
        ).json()
        assert (
            admin.post(
                "/api/v1/alerts/rules", json={"name": "r", "event_type": "backup_failed", "channel_ids": [ch["id"]]}
            ).status_code
            == 201
        )
        assert (
            admin.post(
                "/api/v1/alerts/rules", json={"name": "r", "event_type": "nope", "channel_ids": [ch["id"]]}
            ).status_code
            == 422
        )
        admin.post("/api/v1/devices", json={"hostname": "r1", "management_ip": "10.0.0.1"})
        admin.post("/api/v1/backups/run", json={"run_async": False})  # no credential -> backup_failed
        assert hook.called
        assert "Backup failed: r1" in hook.calls[0].request.content.decode()


def test_netbox_token_scheme_and_error_detail():
    from app.services.integrations.netbox import NetBoxClient, NetBoxError, auth_header

    assert auth_header("0123456789abcdef") == "Token 0123456789abcdef"  # classic / v1
    assert auth_header(" nbt_AbC123.s3cr3t ") == "Bearer nbt_AbC123.s3cr3t"  # NetBox 4.5+ v2
    assert auth_header("Bearer nbt_x.y") == "Bearer nbt_x.y" and auth_header("Token abc") == "Token abc"
    with respx.mock:
        respx.get("https://nb.t/api/dcim/sites/").mock(
            return_value=httpx.Response(403, json={"detail": "Invalid v1 token"})
        )
        import pytest

        with pytest.raises(NetBoxError, match="HTTP 403: Invalid v1 token - check the API token"):
            list(NetBoxClient("https://nb.t", "abc").paginate("/api/dcim/sites/"))


def test_netbox_v2_secret_only_hint():
    from app.services.integrations.netbox import NetBoxClient, NetBoxError

    with respx.mock:
        respx.get("https://nb.t/api/dcim/sites/").mock(
            return_value=httpx.Response(403, json={"detail": "Invalid v1 token"})
        )
        import pytest

        with pytest.raises(NetBoxError, match="only the secret of a NetBox v2 token"):
            list(NetBoxClient("https://nb.t", "yxcphP6gYcm8PG2tSRVL3z0jk2TYXx6foVJkMTzt").paginate("/api/dcim/sites/"))
        with pytest.raises(NetBoxError, match="check the API token"):  # a genuine (hex) v1 token: generic hint
            list(NetBoxClient("https://nb.t", "0123456789abcdef0123456789abcdef01234567").paginate("/api/dcim/sites/"))
