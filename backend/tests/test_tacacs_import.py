import subprocess

import pytest

from app.services.tacacs.shrubbery import ParseError, build_plan, cmd_regex, parse
from tests.test_unit_tacacs import _tacplus_bin

SHRUBBERY = r"""
# Shrubbery tac_plus F4.0.4.27a
key = "gl0bal-key"
accounting file = /var/log/tac_plus.acct
default authentication = file /etc/passwd

host = 10.20.0.1 {
    key = "mx-key"
}
host = 10.30.0.0/24 {
    key = "sw-key"
    prompt = "Welcome"
}
host = 10.40.0.9 { }

acl = mgmt {
    permit = ^10\.
}

group = readonly {
    default service = deny
    service = exec { priv-lvl = 1 }
    service = junos-exec { local-user-name = remote-ro }
    cmd = show { permit .* }
    cmd = ping { permit .* }
}

group = noc {
    member = readonly
    service = exec { priv-lvl = 7 }
    cmd = clear { permit "^counters" deny .* }
}

group = admins {
    default service = permit
    service = exec { priv-lvl = 15 }
    service = junos-exec {
        local-user-name = remote-su
        deny-commands = "^request system zeroize"
    }
    service = fortigate { admin_prof = super_admin }
    cmd = reload { deny .* }
    acl = mgmt
}

user = shashank {
    name = "Shashank K"
    login = des "ab01FAX.bQRSU"
    member = admins
    enable = des "cd02Hz3.aaaaa"
}

user = priya {
    login = cleartext "Pr1ya-Old-Pass"
    member = noc
    expires = "Jan 31 2027"
}

user = arjun {
    login = file /etc/passwd
    member = readonly
    cmd = configure { permit terminal }
}

user = ghost {
    member = nosuchgroup
}
"""


def test_tokenizer_and_parser():
    cfg = parse(SHRUBBERY)
    assert cfg.key == "gl0bal-key"
    assert [h.address for h in cfg.hosts] == ["10.20.0.1", "10.30.0.0/24", "10.40.0.9"]
    assert cfg.groups["noc"].members == ["readonly"]
    assert cfg.groups["admins"].services["junos-exec"]["deny-commands"] == "^request system zeroize"
    assert cfg.users["shashank"].login == ("des", "ab01FAX.bQRSU")
    assert cfg.users["arjun"].cmds[0].rules == [("permit", "terminal")]
    with pytest.raises(ParseError, match="line 2"):
        parse("user = x {\n  frobnicate = 1\n}")
    with pytest.raises(ParseError, match="unterminated"):
        parse('key = "oops')


def test_cmd_regex_conversion():
    assert cmd_regex("show", ".*") == "^show( |$)"
    assert cmd_regex("clear", "^counters") == "^clear counters"
    assert cmd_regex("configure", "terminal") == "^configure .*(terminal)"


def test_plan_semantics():
    plan = build_plan(parse(SHRUBBERY))
    nas = {n.address: n.key for n in plan.nas}
    assert nas["10.20.0.1"] == "mx-key" and nas["10.30.0.0/24"] == "sw-key"
    assert nas["10.40.0.9"] == "gl0bal-key"  # host without key uses the global key
    assert nas["0.0.0.0/0"] == nas["::/0"] == "gl0bal-key"
    pols = {p.name: p for p in plan.policies}
    noc = pols["imp-noc"]
    assert noc.privilege_level == 7  # child overrides parent
    assert noc.junos_class == "remote-ro"  # inherited from readonly
    assert ("permit", "^clear counters") in noc.rules and ("permit", "^show( |$)") in noc.rules
    assert noc.default_action == "deny" and noc.priority < pols["imp-readonly"].priority
    adm = pols["imp-admins"]
    assert adm.default_action == "permit" and adm.fortigate_profile == "super_admin"
    assert adm.extra_attributes["juniper"] == {"deny-commands": "^request system zeroize"}
    assert adm.rules == [("deny", "^reload( |$)")]
    # user-level cmd -> personal policy that wins
    assert pols["imp-user-arjun"].priority == 50
    assert ("permit", "^configure .*(terminal)") in pols["imp-user-arjun"].rules
    users = {u.username: u for u in plan.users}
    assert users["shashank"].password_crypt == "ab01FAX.bQRSU"
    assert users["priya"].cleartext == "Pr1ya-Old-Pass" and users["priya"].valid_until.year == 2027
    assert users["priya"].groups == ["noc", "readonly"]
    assert users["arjun"].groups[0] == "user-arjun" and users["arjun"].password_crypt is None
    w = "\n".join(plan.warnings)
    for expected in (
        "acl 'mgmt'",
        "default authentication",
        "login = file",
        "undefined group 'nosuchgroup'",
        "enable ignored",
        "accounting",
    ):
        assert expected in w


def test_import_dry_run_then_apply(admin, db):
    admin.post("/api/v1/devices", json={"hostname": "mx204-blr", "management_ip": "10.20.0.1"})
    r = admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY})
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["dry_run"] and "mx204-blr (10.20.0.1)" in dry["created"]["nas"]
    assert "user shashank" in dry["rendered"] and 'key = "***"' in dry["rendered"]
    assert sorted(dry["users_needing_password"]) == ["arjun", "ghost"]
    # dry run changed nothing
    assert admin.get("/api/v1/tacacs/policies").json() == []
    assert admin.get("/api/v1/tacacs/devices").json() == []

    real = admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY, "dry_run": False}).json()
    assert len(real["created"]["policies"]) == 4 and len(real["created"]["mappings"]) == 4
    nas = {n["address"]: n for n in admin.get("/api/v1/tacacs/devices").json()}
    assert nas["10.20.0.1"]["device_id"] and nas["10.20.0.1"]["name"] == "mx204-blr"
    maps = {m["tacacs_username"]: m for m in admin.get("/api/v1/tacacs/users").json()}
    assert maps["shashank"]["has_password"] and maps["priya"]["has_password"] and not maps["arjun"]["has_password"]
    # re-import is idempotent: everything skipped
    again = admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY, "dry_run": False}).json()
    assert not any(again["created"].values())
    assert admin.get("/api/v1/audit", params={"action": "tacacs.import"}).json()["total"] == 2
    bad = admin.post("/api/v1/tacacs/import", json={"content": "user = x { wat = 1 }"})
    assert bad.status_code == 422 and "line 1" in bad.text


@pytest.mark.skipif(_tacplus_bin() is None, reason="tac_plus-ng binary not available")
def test_imported_config_accepted_by_tac_plus_ng(admin, db, tenant, tmp_path):
    admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY, "dry_run": False})
    from app.services.tacacs.builder import render_for_tenant

    cfg = tmp_path / "tac.cfg"
    cfg.write_text(render_for_tenant(db, tenant.id).content)
    proc = subprocess.run([_tacplus_bin(), "-P", str(cfg)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_second_server_import_reports_conflicts(admin):
    assert admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY, "dry_run": False}).status_code == 200
    server2 = (
        SHRUBBERY.replace('key = "mx-key"', 'key = "mx-key-OTHER"')  # NAS key differs
        .replace('login = cleartext "Pr1ya-Old-Pass"', 'login = cleartext "Pr1ya-Other!"')  # password differs
        .replace('login = des "ab01FAX.bQRSU"', 'login = des "zz9fQkR2mJxYw"')  # hash differs
        .replace("service = exec { priv-lvl = 7 }", "service = exec { priv-lvl = 10 }")  # policy differs
        .replace(
            "    member = readonly\n    cmd = configure", "    member = readonly\n    member = noc\n    cmd = configure"
        )
        + '\nuser = meera {\n    login = des "mm12aBcDeFgHi"\n    member = readonly\n}\n'
    )
    r = admin.post("/api/v1/tacacs/import", json={"content": server2}).json()
    c = "\n".join(r["conflicts"])
    assert "NAS 10.20.0.1: shared key differs" in c
    assert "user priya: password differs" in c
    assert "user shashank: password hash differs" in c
    assert "policy imp-noc" in c and "priv-lvl 7 in portal vs 10 in file" in c
    assert r["created"]["mappings"] == ["meera"]
    assert any("arjun: added to group(s) noc" in u for u in r["updated"])
    # unchanged objects are not reported as conflicts
    assert "readonly" not in c and "10.30.0.0/24" not in c
    # identical file -> no conflicts at all
    same = admin.post("/api/v1/tacacs/import", json={"content": SHRUBBERY}).json()
    assert same["conflicts"] == [] and not any(same["created"].values())
