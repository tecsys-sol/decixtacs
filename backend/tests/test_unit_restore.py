import subprocess

from scrapli.response import Response
from scrapli_cfg.platform.core.juniper_junos import ScrapliCfgJunos

from app.services import restore

JUNOS_SET = """set system host-name mx204-blr
set interfaces ae0 unit 446 description "Peer's VLAN"
set interfaces ae0 unit 446 vlan-id 446
"""


class FakeConn:
    """Stands in for a scrapli NetworkDriver: records what scrapli-cfg sends, answers canned output."""

    host, port = "mx204-blr", 22

    def __init__(self, answers=None):
        self.sent: list[tuple[str, str]] = []
        self.answers = answers or {}

    def isalive(self):
        return True

    def _resp(self, cmd):
        r = Response(host=self.host, channel_input=cmd, failed_when_contains=["syntax error"])
        out = next((v for k, v in self.answers.items() if cmd.startswith(k)), "")
        r.record_response(out.encode())
        return r

    def send_command(self, command, **kw):
        self.sent.append(("command", command))
        return self._resp(command)

    def send_config(self, config, privilege_level="", **kw):
        self.sent.append((privilege_level or "configuration", config))
        return self._resp(config)


def test_junos_set_config_is_loaded_as_delete_plus_set():
    payload, kwargs = restore.junos_load_plan("## Last commit: x\n" + JUNOS_SET)
    assert kwargs == {"replace": False, "set": True}
    lines = payload.splitlines()
    assert lines[0] == "delete" and lines[1] == "set system host-name mx204-blr"
    # single quotes survive scrapli-cfg's  echo >> file '<line>'  wrapper
    wrapped = f"echo '{lines[2]}'"
    assert subprocess.run(["sh", "-c", wrapped], capture_output=True, text=True).stdout.strip() == (
        'set interfaces ae0 unit 446 description "Peer\'s VLAN"'
    )
    assert restore.is_junos_set_format(JUNOS_SET)
    hier = "system {\n    host-name mx204-blr;\n}\n"
    assert not restore.is_junos_set_format(hier)
    assert restore.junos_load_plan(hier) == (hier.rstrip("\n"), {"replace": True})


def test_junos_push_dry_run_through_real_scrapli_cfg(tmp_path):
    conn = FakeConn(answers={"show | compare": "[edit interfaces ae0]\n+   unit 446 { vlan-id 446; }"})
    cfg = ScrapliCfgJunos(conn=conn, ignore_version=True)
    cfg.prepare()
    out = restore.push_with_cfg(cfg, "junos", JUNOS_SET, dry_run=True)
    assert out.ok and "unit 446" in out.device_diff
    shell = next(c for p, c in conn.sent if p == "root_shell" and c.startswith("echo"))
    # replay the shell commands scrapli-cfg would run on the box: the candidate file is exactly
    # "delete" + the stored set lines
    script = shell.replace("/config/", f"{tmp_path}/")
    subprocess.run(["sh", "-c", script], check=True)
    (candidate,) = tmp_path.iterdir()
    assert candidate.read_text() == "delete\n" + JUNOS_SET
    configuration = [c for p, c in conn.sent if p == "configuration"]
    assert configuration[0].startswith("load set /config/scrapli_cfg_")  # not "load override"
    assert "show | compare" in configuration and "rollback 0" in configuration and "commit" not in configuration


def test_junos_push_commit_and_load_error():
    conn = FakeConn()
    cfg = ScrapliCfgJunos(conn=conn, ignore_version=True)
    cfg.prepare()
    assert restore.push_with_cfg(cfg, "junos", JUNOS_SET, dry_run=False).ok
    assert "commit" in [c for p, c in conn.sent if p == "configuration"]

    bad = FakeConn(answers={"load set": "error: syntax error: foo\nload complete (1 errors)"})
    cfg = ScrapliCfgJunos(conn=bad, ignore_version=True)
    cfg.prepare()
    out = restore.push_with_cfg(cfg, "junos", JUNOS_SET, dry_run=False)
    assert not out.ok and "syntax error" in out.output
    assert "commit" not in [c for p, c in bad.sent] and "rollback 0" in [c for p, c in bad.sent]


def test_hierarchical_junos_uses_load_override():
    conn = FakeConn()
    cfg = ScrapliCfgJunos(conn=conn, ignore_version=True)
    cfg.prepare()
    restore.push_with_cfg(cfg, "junos", "system {\n    host-name r1;\n}\n", dry_run=True)
    assert any(c.startswith("load override /config/") for p, c in conn.sent)


def test_other_platforms_keep_native_replace():
    calls = []

    class Cfg:
        def load_config(self, config, **kw):
            calls.append(kw)
            return type("R", (), {"failed": False, "result": "", "scrapli_responses": []})()

        def diff_config(self):
            return type("D", (), {"device_diff": "", "unified_diff": "-a\n+b"})()

        def abort_config(self):
            calls.append("abort")

    out = restore.push_with_cfg(Cfg(), "eos", "hostname a\n", dry_run=True)
    assert out.ok and out.device_diff == "-a\n+b" and calls == [{"replace": True}, "abort"]
