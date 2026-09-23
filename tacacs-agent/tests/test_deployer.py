from __future__ import annotations

import hashlib
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from nom_tacacs_agent.api import AgentAPI, ApiError, ConfigResponse
from nom_tacacs_agent.deployer import (
    ConfigDeployer,
    ReloadError,
    ValidationResult,
    command_reloader,
    signal_reloader,
    tacplus_validator,
)

OLD = "id = spawnd { listen = { port = 49 } }\n# old\n"
NEW = "id = spawnd { listen = { port = 49 } }\n# new\n"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Recorder:
    def __init__(self, ok=True, output="", fail_times=0):
        self.calls: list[str] = []
        self.ok, self.output, self.fail_times = ok, output, fail_times

    def validate(self, path: Path) -> ValidationResult:
        self.calls.append(path.read_text())
        return ValidationResult(self.ok, self.output)

    def reload(self) -> None:
        self.calls.append("reload")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ReloadError("boom")


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "etc" / "tac_plus-ng.cfg"
    p.parent.mkdir()
    p.write_text(OLD)
    return p


def changed(content=NEW, version=7, etag=None):
    return ConfigResponse("changed", content=content, etag=etag or sha(content), version=version)


def test_successful_deploy_swaps_atomically_and_reloads(cfg, fake_api):
    fake_api.config = changed()
    v, r = Recorder(), Recorder()
    d = ConfigDeployer(fake_api, cfg, v.validate, r.reload)
    assert d.running_sha == sha(OLD)
    out = d.sync_once()
    assert out.action == "deployed"
    assert cfg.read_text() == NEW
    assert v.calls == [NEW]  # validated the candidate content
    assert r.calls == ["reload"]
    assert d.running_sha == sha(NEW)
    assert fake_api.etags_sent == [sha(OLD)]  # If-None-Match carries the running sha
    assert fake_api.heartbeats[-1][:2] == (sha(NEW), "ok")
    assert not d.candidate_path.exists()
    assert d.previous_path.read_text() == OLD
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o640
    # next poll: server answers 304 -> nothing happens
    out = d.sync_once()
    assert out.action == "unchanged"
    assert r.calls == ["reload"]
    assert fake_api.etags_sent[-1] == sha(NEW)


def test_validation_failure_keeps_running_config(cfg, fake_api):
    fake_api.config = changed()
    v, r = Recorder(ok=False, output="line 3: unknown keyword"), Recorder()
    d = ConfigDeployer(fake_api, cfg, v.validate, r.reload)
    out = d.sync_once()
    assert out.action == "rejected"
    assert cfg.read_text() == OLD
    assert r.calls == []
    assert d.running_sha == sha(OLD)
    running, status, msg = fake_api.heartbeats[-1]
    assert (running, status) == (sha(OLD), "error")
    assert "unknown keyword" in msg
    assert not d.candidate_path.exists()
    # the same bad revision is not re-validated on every poll, but the error keeps being reported
    d.sync_once()
    assert len(v.calls) == 1
    assert fake_api.heartbeats[-1][1] == "error"


def test_reload_failure_rolls_back(cfg, fake_api):
    fake_api.config = changed()
    v, r = Recorder(), Recorder(fail_times=1)
    d = ConfigDeployer(fake_api, cfg, v.validate, r.reload)
    out = d.sync_once()
    assert out.action == "rolled_back"
    assert cfg.read_text() == OLD
    assert r.calls == ["reload", "reload"]  # failed reload + reload of the restored file
    assert d.running_sha == sha(OLD)
    assert fake_api.heartbeats[-1][1] == "error"
    assert "rolled back" in fake_api.heartbeats[-1][2]


def test_etag_mismatch_is_rejected(cfg, fake_api):
    fake_api.config = changed(etag="0" * 64)
    v, r = Recorder(), Recorder()
    out = ConfigDeployer(fake_api, cfg, v.validate, r.reload).sync_once()
    assert out.action == "rejected"
    assert v.calls == [] and r.calls == []
    assert cfg.read_text() == OLD


@pytest.mark.parametrize("state", ["not_deployed", "conflict"])
def test_not_deployed_or_conflict_keeps_config(cfg, fake_api, state):
    fake_api.config = ConfigResponse(state, detail="x")
    v, r = Recorder(), Recorder()
    out = ConfigDeployer(fake_api, cfg, v.validate, r.reload).sync_once()
    assert out.action == state
    assert cfg.read_text() == OLD
    assert fake_api.heartbeats[-1][1] == "ok"


def test_fetch_error_does_not_touch_anything(cfg, fake_api):
    fake_api.fetch_error = ApiError("down")
    out = ConfigDeployer(fake_api, cfg, Recorder().validate, Recorder().reload).sync_once()
    assert out.action == "error"
    assert fake_api.heartbeats == []


def test_first_deploy_without_existing_file(tmp_path, fake_api):
    cfg = tmp_path / "new" / "tac_plus-ng.cfg"
    fake_api.config = changed()
    d = ConfigDeployer(fake_api, cfg, Recorder().validate, Recorder().reload)
    assert d.running_sha is None
    assert d.sync_once().action == "deployed"
    assert cfg.read_text() == NEW


# --- real subprocess based validator / reloaders ------------------------------------------------


def fake_tacplus(tmp_path: Path) -> str:
    script = tmp_path / "tac_plus-ng"
    script.write_text('#!/bin/sh\n[ "$1" = "-P" ] || exit 2\n'
                      'if grep -q BROKEN "$2"; then echo "parse error: BROKEN" >&2; exit 1; fi\nexit 0\n')
    script.chmod(0o755)
    return str(script)


def test_tacplus_validator_runs_binary(tmp_path):
    validate = tacplus_validator(fake_tacplus(tmp_path))
    good = tmp_path / "good.cfg"
    good.write_text(NEW)
    bad = tmp_path / "bad.cfg"
    bad.write_text("BROKEN\n")
    assert validate(good).ok
    res = validate(bad)
    assert not res.ok and "parse error" in res.output
    assert not tacplus_validator(str(tmp_path / "missing"))(good).ok


def test_end_to_end_with_fake_binary(cfg, fake_api, tmp_path):
    fake_api.config = changed(content="BROKEN\n")
    d = ConfigDeployer(fake_api, cfg, tacplus_validator(fake_tacplus(tmp_path)), Recorder().reload)
    assert d.sync_once().action == "rejected"
    assert cfg.read_text() == OLD


def test_signal_reloader_sends_sighup(tmp_path):
    flag = tmp_path / "hup"
    ready = tmp_path / "ready"
    code = (
        "import signal,sys,time,pathlib\n"
        f"signal.signal(signal.SIGHUP, lambda *a: pathlib.Path({str(flag)!r}).write_text('1'))\n"
        f"pathlib.Path({str(ready)!r}).write_text('1')\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        pidfile = tmp_path / "tac.pid"
        pidfile.write_text(f"{proc.pid}\n")
        signal_reloader(pidfile, settle=0.2)()
        assert flag.exists()
    finally:
        proc.kill()
        proc.wait()


def test_signal_reloader_errors(tmp_path):
    with pytest.raises(ReloadError):
        signal_reloader(tmp_path / "missing.pid")()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    pidfile = tmp_path / "dead.pid"
    pidfile.write_text(str(dead.pid))
    with pytest.raises(ReloadError):
        signal_reloader(pidfile, sig=signal.SIGHUP, settle=0)()


def test_command_reloader(tmp_path):
    command_reloader("true")()
    with pytest.raises(ReloadError):
        command_reloader("false")()


# --- HTTP wiring of AgentAPI.fetch_config ------------------------------------------------------------


def test_agent_api_config_http_semantics():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["inm"] = request.headers.get("if-none-match")
        inm = request.headers.get("if-none-match")
        if inm == sha(NEW):
            return httpx.Response(304)
        if inm == "conflict":
            return httpx.Response(409, json={"detail": "redeploy"})
        return httpx.Response(200, text=NEW, headers={"ETag": sha(NEW), "X-Config-Version": "3"})

    api = AgentAPI("http://nom/api/v1", "nomagent_x", transport=httpx.MockTransport(handler))
    r = api.fetch_config(None)
    assert (r.state, r.content, r.etag, r.version) == ("changed", NEW, sha(NEW), 3)
    assert seen["auth"] == "Bearer nomagent_x" and seen["inm"] is None
    assert api.fetch_config(sha(NEW)).state == "unchanged"
    c = api.fetch_config("conflict")
    assert c.state == "conflict" and c.detail == "redeploy"


def test_agent_api_errors_are_classified():
    api = AgentAPI("http://nom/api/v1", "t", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(ApiError) as e:
        api.ingest(["x"])
    assert e.value.retryable and not e.value.permanent
    unprocessable = httpx.MockTransport(lambda r: httpx.Response(422, json={"detail": "bad"}))
    api = AgentAPI("http://nom/api/v1", "t", transport=unprocessable)
    with pytest.raises(ApiError) as e:
        api.ingest(["x"])
    assert e.value.permanent

    def boom(request):
        raise httpx.ConnectError("refused")

    api = AgentAPI("http://nom/api/v1", "t", transport=httpx.MockTransport(boom))
    with pytest.raises(ApiError) as e:
        api.heartbeat("x")
    assert e.value.status_code is None and e.value.retryable


def test_permissions_of_candidate(cfg, fake_api):
    fake_api.config = changed()
    seen = {}

    def validate(path: Path):
        seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
        seen["dir"] = path.parent
        return ValidationResult(True)

    ConfigDeployer(fake_api, cfg, validate, lambda: None).sync_once()
    assert seen["mode"] == 0o640
    assert seen["dir"] == cfg.parent  # same filesystem -> os.replace is atomic
