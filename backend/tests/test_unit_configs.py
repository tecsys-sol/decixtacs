from app.services import diff
from app.services.backup.git_store import GitConfigStore
from app.services.backup.sanitize import prepare
from app.services.compliance.engine import DEFAULT_RULES, Rule, evaluate, evaluate_rule
from app.services.drift import compare_golden, compare_running
from app.services.intel.parser import parse
from app.services.risk import analyse_diff, classify_command

JUNOS = """## Last commit: 2026-09-23 10:00:00 UTC by shashank
set system host-name mx204-blr
set system services ssh protocol-version v2
set system ntp server 10.0.0.10
set system ntp server 10.0.0.11
set system syslog host 10.0.0.20 any notice
set system tacplus-server 10.0.0.5 secret "$9$abcdef"
set system login user ops authentication encrypted-password "$6$xyz"
set snmp community public authorization read-only
set interfaces ae0 unit 446 vlan-id 446
set protocols bgp group TRANSIT neighbor 10.0.0.2 peer-as 13335
set policy-options community IX members 65000:100
"""


def test_sanitize_removes_volatile_and_secrets():
    out = prepare(JUNOS, "junos", sanitize=True)
    assert "Last commit" not in out
    assert "$9$abcdef" not in out and "$6$xyz" not in out
    assert 'secret "<removed>"' in out
    assert prepare(JUNOS, "junos", sanitize=False).count("$9$abcdef") == 1


def test_diff_views():
    a = "a\nb\nc\n"
    b = "a\nB\nc\nd\n"
    uni = diff.unified(a, b)
    assert "-b" in uni and "+B" in uni and "+d" in uni
    st = diff.stats(a, b)
    assert (st.added, st.removed) == (2, 1)
    rows = diff.side_by_side(a, b)
    assert [r["type"] for r in rows] == ["equal", "modified", "equal", "added"]
    assert {r["type"] for r in diff.inline(a, b)} == {"equal", "added", "removed"}


def test_side_by_side_context_skip():
    a = "\n".join(f"l{i}" for i in range(40))
    rows = diff.side_by_side(a, a.replace("l20", "X"), context=2)
    assert rows[0]["type"] == "skip" and rows[-1]["type"] == "skip"
    assert sum(r["type"] == "equal" for r in rows) == 4


def test_compliance_rules():
    rules = [Rule(str(i), r["name"], r["rule_type"], r["pattern"], r["severity"], r.get("block_start"),
                  r.get("min_count", 1), tuple(r.get("platforms", []))) for i, r in enumerate(DEFAULT_RULES)]
    results, score = evaluate(rules, JUNOS, "junos")
    by_name = {rules[int(r.rule_id)].name: r for r in results}
    assert not by_name["SNMP community must not be public"].passed
    assert by_name["At least two NTP servers"].passed
    assert by_name["Syslog server configured"].passed
    assert by_name["TACACS+ authentication configured (Junos)"].passed
    assert "SSH v2 only (IOS)" not in by_name  # platform filtered
    assert 0 < score < 100


def test_block_rule():
    cfg = "router bgp 65000\n neighbor 1.1.1.1 remote-as 1\n neighbor 1.1.1.1 description x\n"
    r = Rule("1", "desc", "block_must_match", r"description", block_start=r"^router bgp")
    assert evaluate_rule(r, cfg).passed
    assert not evaluate_rule(r, "router bgp 1\n neighbor 2.2.2.2 remote-as 2\n").passed
    assert "invalid pattern" in evaluate_rule(Rule("2", "bad", "must_match", "("), cfg).detail


def test_intel_junos_and_ios():
    objs = parse(JUNOS, "junos")
    nb = [o for o in objs if o.kind == "bgp_neighbor"][0]
    assert nb.key == "10.0.0.2" and nb.attributes["peer_as"] == 13335
    assert any(o.kind == "community_value" and o.key == "65000:100" for o in objs)
    assert any(o.kind == "vlan" and o.key == "446" for o in objs)
    ios = "router bgp 65000\n neighbor 192.0.2.1 remote-as 13335\n neighbor 192.0.2.1 description CF\n" \
          "ip prefix-list XYZ seq 5 permit 10.0.0.0/8\nip community-list standard IX permit 65000:100\n"
    objs = parse(ios, "eos")
    assert any(o.kind == "bgp_neighbor" and o.attributes["peer_as"] == 13335 for o in objs)
    assert any(o.kind == "prefix_list" and o.key == "XYZ" for o in objs)


def test_risk_analysis():
    d = "--- a\n+++ b\n@@\n-set protocols bgp group TRANSIT neighbor 10.0.0.2 peer-as 13335\n+set system services telnet\n"
    r = analyse_diff(d)
    assert r.score >= 40 and r.level in ("high", "critical") and len(r.findings) == 2
    assert analyse_diff("+set interfaces ae0 description foo\n").level == "low"
    assert classify_command("request system reboot") and not classify_command("show version")


def test_drift():
    assert compare_golden(JUNOS, "set system ntp server 10.0.0.10\nset system ntp server 9.9.9.9\n", "snippet").missing_lines \
        == ["set system ntp server 9.9.9.9"]
    assert not compare_running("a\nb\n", "a\nb\n").drifted
    assert compare_running("a\nc\n", "a\nb\n").drifted


def test_git_store(tmp_path):
    s = GitConfigStore(str(tmp_path), "t1")
    p = s.relpath("blr", "mx204-blr")
    sha1 = s.write(p, "v1\n", author="shashank", author_email=None, subject="init", trailers={"Reason": "x"})
    assert sha1 and s.write(p, "v1\n", author="x", author_email=None, subject="noop", trailers={}) is None
    sha2 = s.write(p, "v2\n", author="bob", author_email=None, subject="Added new IX VLAN", trailers={"Reason": "vlan"})
    assert s.read(p, sha1) == "v1\n" and s.read(p) == "v2\n"
    hist = s.history(p)
    assert [h.sha for h in hist] == [sha2, sha1] and hist[0].author == "bob"
    assert "Reason: vlan" in hist[0].message
