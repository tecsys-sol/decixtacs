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
    assert "password login = crypt $6$abc$def" in c
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
    ld = g.LdapBackend("microsoft", "ldaps://dc1", "dc=x", "cn=svc", "pw")
    c = _render(settings=g.ServerSettings(ldap=ld)).content
    assert "mavis module = external" in c and "user backend = mavis" in c


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


def test_parse_json_and_garbage():
    r = parse_line(
        '{"timestamp":"2026-09-23T10:00:00+00:00","user":"a","device":"10.0.0.1","type":"stop","cmd":"show bgp summary"}'
    )
    assert r.command == "show bgp summary" and r.kind == "acct"
    assert parse_line("") is None
    assert parse_line("not\ta\tvalid") is None
