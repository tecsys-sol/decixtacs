from __future__ import annotations

import os
import signal
import sys
import threading
import time

from nom_tacacs_agent.config import Settings
from nom_tacacs_agent.supervisor import Supervisor


def test_supervisor_installs_bootstrap_writes_pid_restarts_and_stops(tmp_path, monkeypatch):
    boot = tmp_path / "boot.cfg"
    boot.write_text("# bootstrap\n")
    s = Settings(config_path=tmp_path / "etc" / "tac.cfg", bootstrap_config=boot,
                 pidfile=tmp_path / "run" / "tac.pid", state_dir=tmp_path / "state",
                 log_files=[str(tmp_path / "log" / "acct.log")])
    sup = Supervisor(s)
    # stand-ins: a long running "tac_plus-ng" and an "agent" that exits immediately (-> restarted)
    sup.children[0].argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    sup.children[1].argv = [sys.executable, "-c", "pass"]
    monkeypatch.setattr(signal, "signal", lambda *a: None)  # not in main thread
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("rc", sup.run()))
    t.start()
    try:
        for _ in range(100):
            if s.pidfile.exists():
                break
            time.sleep(0.05)
        pid = int(s.pidfile.read_text())
        os.kill(pid, 0)
        assert s.config_path.read_text() == "# bootstrap\n"
        assert (tmp_path / "log").is_dir()
        time.sleep(2.5)
        assert sup.children[1].backoff.attempt >= 1  # agent was restarted
    finally:
        sup.stopping = True
        t.join(15)
    assert result["rc"] == 0
    assert not s.pidfile.exists()
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive or os.waitpid(pid, os.WNOHANG) is not None


def test_settings_from_env(tmp_path):
    tok = tmp_path / "tok"
    tok.write_text("nomagent_abc\n")
    s = Settings.from_env({"NOM_AGENT_API_URL": "https://nom.example.net/", "NOM_AGENT_TOKEN_FILE": str(tok),
                           "NOM_AGENT_LOG_FILES": "/a.log, /b.log", "NOM_AGENT_SPOOL_DIR": ""})
    assert s.base_url == "https://nom.example.net/api/v1"
    assert s.token == "nomagent_abc"
    assert s.log_files == ["/a.log", "/b.log"]
    assert s.spool_dir is None
    assert s.validate() == []
    assert Settings.from_env({}).validate()  # api url + token missing
