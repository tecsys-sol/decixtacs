import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.tacacs import generator as g
from app.services.tacacs.accounting import parse_line
from app.services.tacacs.crypt import tacacs_crypt, tacacs_verify
from app.services.tacacs.ingest import normalize_result


def _render(**kw):
    nas = [
        g.NasEntry("mx204-blr", "10.0.0.1", 's3cr"et', "juniper", ["core-routers"]),
        g.NasEntry("fw1", "10.0.1.1", "k2", "fortinet"),
        g.NasEntry("mt1", "10.0.0.9", "x", "mikrotik"),
    ]
    profiles = [
        g.Profile(
            "noc-ro",
            "noc",
            privilege_level=1,
            device_tags=["core-routers"],
            commands=[g.CommandRule("permit", "^show "), g.CommandRule("deny", "^request system reboot", 5)],
        ),
        g.Profile("admins", "neteng", priority=10, privilege_level=15, default_action="permit"),
    ]
    users = [g.TacUser("shashank", ["noc"], password_crypt="$6$abc$def"), g.TacUser("ldapuser", ["neteng"], "ldap")]
    return g.render(nas, profiles, users, **kw)


def test_render_structure():
    r = _render()
    c = r.content
    assert c.startswith("# ----")
    assert "id = spawnd {" in c and "id = tac_plus-ng {" in c
    assert 'key = "s3cr\\"et"' in c  # quotes escaped
    assert "tag = core-routers" in c
    assert 'password login = crypt "$6$abc$def"' in c  # quoted: "rounds=" would split the token
    assert "password login = mavis" in c
    assert "if (member == noc && device.tag == core-routers) { profile = noc-ro permit }" in c
    # rules ordered by priority: admins (10) before noc-ro (100)
    assert c.index("rule admins") < c.index("rule noc-ro")
    # command rules ordered by sequence (deny seq 5 before permit seq 10)
    assert c.index("^request system reboot") < c.index("if (cmd =~ /^show /) permit")
    assert c.count("{") == c.count("}")


def test_vendor_blocks():
    c = _render().content
    assert "set local-user-name" in c and 'set deny-commands = "(^request system reboot)"' in c
    assert 'set admin_prof = "super_admin"' in c  # priv 15 -> super_admin
    assert "set priv-lvl = 15" in c


def test_mikrotik_skipped_with_warning():
    r = _render()
    assert "device mt1" not in r.content
    assert any("mikrotik" in w for w in r.warnings)


def test_render_is_deterministic():
    assert _render().sha256 == _render().sha256


def test_redaction():
    red = g.redact_keys(_render().content)
    assert "s3cr" not in red and 'key = "***"' in red


def test_ldap_backend_block():
    ld = g.LdapBackend("microsoft", "ldaps://dc1", "dc=x", "cn=svc", "pw", group_prefix="tac-", exec_path="/x/ldap.pl")
    c = _render(settings=g.ServerSettings(ldap=ld)).content
    assert "mavis module = external" in c and "user backend = mavis" in c
    assert 'exec = "/x/ldap.pl"' in c
    # mavis_tacplus-ng_ldap.pl reads LDAP_MEMBEROF_REGEX (it has no TACACS_GROUP_PREFIX/LDAP_SERVER_TYPE)
    assert 'setenv LDAP_MEMBEROF_REGEX = "^cn=tac\\\\-([^,]+),.*"' in c
    assert "TACACS_GROUP_PREFIX" not in c and "LDAP_SERVER_TYPE" not in c


def test_time_window_uses_time_object():
    p = g.Profile("night", "noc", timespan="* 8-20 * * 1-5")
    c = g.render([], [p], []).content
    assert 'time ts-night { "* 8-20 * * 1-5" }' in c and "timespan" not in c
    assert "&& time == ts-night)" in c


def test_explicit_log_formats():
    c = _render(settings=g.ServerSettings(access_log="/l/a.log", authz_log="/l/z.log", acct_log="/l/c.log")).content
    assert 'destination = "/l/a.log"' in c and 'destination = "/l/c.log"' in c
    assert c.count('prefix = "${TIMESTAMP}${FS}"') == 3
    assert "access format = " in c and "authorization format = " in c and "accounting format = " in c
    assert "${priv-lvl}" in c and "${privlvl}" not in c  # the documented ${privlvl} is not a valid token
    assert "${client.address}" in c and "${client}" not in c  # ${client} is never filled in
    assert "pap password = login" in c


def _tacplus_bin() -> str | None:
    for cand in (
        os.environ.get("NOM_TACPLUS_BIN"),
        shutil.which("tac_plus-ng"),
        "/usr/local/sbin/tac_plus-ng",
        str(Path.home() / ".cache/nom-e2e/tac_plus-ng/sbin/tac_plus-ng"),
    ):
        if cand and os.access(cand, os.X_OK):
            return cand
    return None


@pytest.mark.skipif(_tacplus_bin() is None, reason="tac_plus-ng binary not available")
def test_rendered_config_accepted_by_tac_plus_ng(tmp_path):
    """The real parser (tac_plus-ng -P) must accept everything the generator can emit."""
    nas = [
        g.NasEntry("core-r1", "10.0.0.1", 's3"c\\ret', "juniper", ["core", "ams"]),
        g.NasEntry("edge sw", "10.0.1.0/24", "k2", "arista"),
        g.NasEntry("fw1", "10.0.2.1", "k3", "fortinet", ["fw"]),
        g.NasEntry("sophos1", "10.0.2.2", "k4", "sophos"),
        g.NasEntry("mt1", "10.0.3.1", "k5", "mikrotik"),
        g.NasEntry("ios1", "2001:db8::1", "k6", "cisco", ["lab"]),
    ]
    profiles = [
        g.Profile(
            "noc-ro",
            "noc",
            priority=50,
            device_tags=["core", "lab"],
            commands=[g.CommandRule("permit", "^show .*"), g.CommandRule("deny", "^show running-config", 5)],
            timespan="* 8-20 * * 1-5",
        ),
        g.Profile(
            "admins",
            "neteng",
            privilege_level=15,
            default_action="permit",
            commands=[g.CommandRule("deny", "^reload|^request system (reboot|halt)")],
            junos_class="super-user",
            fortigate_profile="super_admin",
            arista_role="network-admin",
            extra_attributes={"shell": {"foo": "bar"}, "juniper": {"x": "y"}, "fortinet": {"vdom": "root"}},
        ),
        g.Profile("fw-ops", "fw ops", device_tags=["fw"], timespan="Wk0800-1800,Sa"),
    ]
    users = [
        g.TacUser("alice", ["noc"], password_crypt=tacacs_crypt("S3cure-Pass!")),
        g.TacUser("bob", ["neteng", "noc"], valid_until="2030-01-01"),  # no password -> deny
        g.TacUser("carol", ["neteng", "fw ops"], auth_method="ldap"),
    ]
    mavis = tmp_path / "mavis_tacplus-ng_ldap.pl"
    mavis.write_text("#!/bin/sh\n")
    mavis.chmod(0o755)
    ld = g.LdapBackend("microsoft", "ldaps://dc1 ldaps://dc2", "dc=ex,dc=com", "cn=b", 'p"w', "tac", str(mavis))
    for ldap in (None, ld):
        s = g.ServerSettings(
            listen_port=4949,
            access_log=str(tmp_path / "access.log"),
            authz_log=str(tmp_path / "authz.log"),
            acct_log=str(tmp_path / "acct.log"),
            syslog_host="127.0.0.1",
            ldap=ldap,
        )
        cfg = tmp_path / "tac_plus-ng.cfg"
        cfg.write_text(g.render(nas, profiles, users, s).content)
        r = subprocess.run([_tacplus_bin(), "-P", str(cfg)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout + r.stderr


def test_ident_and_regex_escaping():
    assert g.ident("core routers/BLR") == "core-routers-BLR"
    assert g.regex_literal("^show a/b") == "/^show a\\/b/"


def test_crypt_roundtrip():
    h = tacacs_crypt("S3cure-Pass!")
    assert h.startswith("$6$") and tacacs_verify("S3cure-Pass!", h)


def test_parse_accounting_tab_format():
    line = "2026-09-23 10:01:02 +0000\t10.0.0.1\tshashank\tssh\t192.0.2.10\tstop\ttask_id=7\tservice=shell\tpriv-lvl=15\tcmd=show version <cr>"
    r = parse_line(line)
    assert r.kind == "acct" and r.username == "shashank" and r.device_address == "10.0.0.1"
    assert r.command == "show version" and r.priv_lvl == 15 and r.task_id == "7"


def test_parse_authz_and_authen():
    r = parse_line(
        "2026-09-23 10:01:02 +0000\t10.0.0.1\tbob\tssh\t192.0.2.10\tdeny\tservice=shell\tcmd=request system reboot"
    )
    assert r.kind == "author" and normalize_result(r.record_type) == "deny"
    r = parse_line("2026-09-23 10:01:02 +0000\t10.0.0.1\tbob\tssh\t192.0.2.10\tshell login failed")
    assert r.kind == "authen" and normalize_result(r.record_type) == "fail"


# Lines captured from tac_plus-ng (d020c75) running a generator-rendered configuration, driven by
# the tacacs_plus client (e2e suite). Access/authorization lines with an empty client field were
# written before the format used ${client.address}.
T = "\t"
REAL_ACCESS_PASS = T.join(
    ["2026-09-23 17:16:29 +0000", "127.0.0.1", "alice-9e138b", "vty0", "198.51.100.7", "AUTHC-PASS",
     "service=login", "authen-type=ascii", "profile=noc-ro-9e138b", "session_id=3863a5a0",
     "detail=shell login succeeded"]
)  # fmt: skip
REAL_ACCESS_FAIL = T.join(
    ["2026-09-23 17:04:24 +0000", "127.0.0.1", "nobody", "tty1", "", "AUTHC-FAIL", "service=login",
     "authen-type=ascii", "profile=", "session_id=2859df89", "detail=shell login failed"]
)  # fmt: skip
REAL_AUTHZ_DENY = T.join(
    ["2026-09-23 17:16:32 +0000", "127.0.0.1", "alice-9e138b", "python_tty0", "python_device", "deny",
     "service=shell", "priv-lvl=0", "profile=noc-ro-9e138b", "rule=noc-ro-9e138b", "session_id=9a7d5b9b",
     "cmd=show running-config <cr>"]
)  # fmt: skip
REAL_AUTHZ_PERMIT = T.join(
    ["2026-09-23 17:04:25 +0000", "127.0.0.1", "alice", "tty1", "", "permit", "service=shell", "priv-lvl=0",
     "profile=noc-ro", "rule=noc-ro", "session_id=e10e9812", "cmd=show version <cr>"]
)  # fmt: skip
REAL_ACCT_STOP = T.join(
    ["2026-09-23 17:16:16 +0000", "127.0.0.1", "alice-9e138b", "vty1", "198.51.100.7", "stop", "service=shell",
     "priv-lvl=0", "session_id=41ca3614", "args=task_id=9001 priv-lvl=15 cmd=configure terminal",
     "cmd=configure terminal"]
)  # fmt: skip


def test_parse_real_tac_plus_ng_lines():
    r = parse_line(REAL_ACCESS_PASS)
    assert (r.kind, r.username, r.device_address, r.port) == ("authen", "alice-9e138b", "127.0.0.1", "vty0")
    assert normalize_result(r.record_type) == "pass" and r.command == "shell login succeeded"
    assert r.source_address == "198.51.100.7" and r.session_id == "3863a5a0"
    r = parse_line(REAL_ACCESS_FAIL)
    assert r.kind == "authen" and normalize_result(r.record_type) == "fail" and r.username == "nobody"
    assert r.source_address is None
    r = parse_line(REAL_AUTHZ_DENY)
    assert r.kind == "author" and normalize_result(r.record_type) == "deny"
    assert r.command == "show running-config" and r.service == "shell"
    r = parse_line(REAL_AUTHZ_PERMIT)
    assert r.kind == "author" and normalize_result(r.record_type) == "permit" and r.command == "show version"
    r = parse_line(REAL_ACCT_STOP)
    assert r.kind == "acct" and r.record_type == "stop" and r.command == "configure terminal"
    assert r.task_id == "9001" and r.priv_lvl == 15  # from the NAS AV pairs in ${args}
    assert r.timestamp.isoformat() == "2026-09-23T17:16:16+00:00"


def test_parse_default_prefix_and_msgids():
    # tac_plus-ng's default file prefix "${TIMESTAMP} " joins timestamp and NAS with a space
    r = parse_line("2026-09-23 17:04:25 +0000 10.0.0.1\talice\ttty1\t192.0.2.1\tstop\tservice=shell\tcmd=show clock")
    assert r.device_address == "10.0.0.1" and r.kind == "acct" and r.command == "show clock"
    r = parse_line("2026-09-23 17:04:25 +0000\t10.0.0.1\talice\ttty1\t\tAUTHZ-FAIL\tcmd=reload")
    assert r.kind == "author" and normalize_result(r.record_type) == "deny"
    r = parse_line("2026-09-23 17:04:25 +0000\t10.0.0.1\talice\ttty1\t\tACCT-START\tcmd=show clock")
    assert r.kind == "acct" and r.record_type == "start"
    r = parse_line("2026-09-23 17:04:25 +0000\t10.0.0.1\talice\ttty1\t\tAUTHC-FAIL-DENY\tdetail=x")
    assert r.kind == "authen" and normalize_result(r.record_type) == "fail"


def test_parse_json_and_garbage():
    r = parse_line(
        '{"timestamp":"2026-09-23T10:00:00+00:00","user":"a","device":"10.0.0.1","type":"stop","cmd":"show bgp summary"}'
    )
    assert r.command == "show bgp summary" and r.kind == "acct"
    assert parse_line("") is None
    assert parse_line("not\ta\tvalid") is None
