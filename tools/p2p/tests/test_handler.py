"""End-to-end test of tools/p2p/sflow-to-rrd-handler: a fake sflowtool, a fake IXP Manager
API, real RRD files. Needs perl with RRDs/JSON/REST::Client and the rrdtool binary;
skipped otherwise. Takes about 90 seconds."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = pathlib.Path(__file__).resolve().parent
HANDLER = HERE.parent / "sflow-to-rrd-handler"
STEP = 2  # seconds per RRD row in the files this test pre-creates

needs = pytest.mark.skipif(
    shutil.which("rrdtool") is None
    or subprocess.run(["perl", "-MRRDs", "-MJSON", "-MREST::Client", "-e1"], capture_output=True).returncode != 0,
    reason="needs rrdtool and perl RRDs, JSON, REST::Client",
)

MACS = {"1": {"100": {f"02{i:010x}": i for i in range(1, 7)}}}
# MACs stored the way a person might type them: the stock handler never matches these
MACS["1"]["100"]["02:00:00:00:00:07".upper()] = 7
# a member on another peering VLAN (tag 200)
MACS["1"]["200"] = {f"02{8:010x}": 8}
# a router MAC configured on both tags: its tag must come from the switch (--agent-vlan)
MACS["1"]["100"][f"02{9:010x}"] = 9
MACS["1"]["200"][f"02{9:010x}"] = 19

# pair 1->2: 20s on, 30s off, 10s on, then off; 3->4 and 7->3 carry steady background traffic
GENERATOR = textwrap.dedent(
    """
    import os, sys, time
    t0 = float(os.environ["T0"]); size, skip = 1000, 10
    def line(s, d, vlan=100):
        head = f"FLOW,10.0.0.1,{s},{d},02{s:010x},02{d:010x},0x0800,{vlan},{vlan},a,b,6,0,64,1,2,0x10"
        return f"{head},{size},{size-18},{skip}\\n"
    while True:
        t = time.time() - t0
        if t > 105: break
        on = 0 <= t < 20 or 50 <= t < 60
        out = line(3, 4) + line(7, 3) + line(4, 6, vlan=0) + line(4, 8, vlan=0) + line(9, 3, vlan=0)
        if on: out += line(1, 2) * 2
        sys.stdout.write(out); sys.stdout.flush()
        time.sleep(0.01)
    """
)


class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(MACS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def rrd_create(path, start):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rrdtool",
            "create",
            str(path),
            "--step",
            str(STEP),
            "--start",
            str(start),
            "DS:traffic_in:GAUGE:600:U:U",
            "DS:traffic_out:GAUGE:600:U:U",
            "RRA:AVERAGE:0.5:1:2000",
            "RRA:MAX:0.5:1:2000",
        ],
        check=True,
    )


def fetch(path, start, end):
    out = subprocess.run(
        ["rrdtool", "fetch", str(path), "AVERAGE", "-r", str(STEP), "-s", str(start), "-e", str(end)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = {}
    for ln in out.splitlines():
        if ":" in ln and ln.split(":")[0].strip().isdigit():
            ts, vals = ln.split(":")
            rows[int(ts)] = [None if "nan" in v else float(v) for v in vals.split()]
    return rows


@needs
def test_idle_pairs_read_zero_and_traffic_is_not_smeared(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gen = tmp_path / "gen.py"
    gen.write_text(GENERATOR)

    t0 = int(time.time()) + 2
    pair = tmp_path / "ipv4/bytes/p2p/src-00001/p2p.ipv4.bytes.src-00001.dst-00002.rrd"
    rrd_create(pair, t0 - 10)

    env = dict(os.environ, SFLOW_HANDLER_NO_CONFIG="1", T0=str(t0))
    proc = subprocess.Popen(
        [
            "perl",
            str(HANDLER),
            "--sflowtool",
            sys.executable,
            "--sflowtool_opts",
            str(gen),
            "--agent-vlan",
            "10.0.0.=100",
            "--flushtimer",
            "2",
            "--idle-refresh",
            "20",
            "--no-rrdcached",
            "--sflow_rrddir",
            str(tmp_path),
            "--apibaseurl",
            f"http://127.0.0.1:{srv.server_port}/api/v4",
            "--apikey",
            "k",
        ],
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(max(0, t0 + 108 - time.time()))
    finally:
        proc.terminate()
        _, err = proc.communicate(timeout=60)
        srv.shutdown()

    assert "WARNING" not in err, err
    flushes = [ln for ln in err.splitlines() if ln.startswith("flush:")]
    assert len(flushes) > 30
    # idle pairs are refreshed every ~20s, so the pair was idle at the flush before it came back
    assert any("prezero=0" not in ln for ln in flushes), "no zero written ahead of a reactivated pair"

    rate = 2 * 100 * 1000 * 10  # two lines per 10ms tick, 1000 bytes, 1-in-10 sampling
    last = int(subprocess.run(["rrdtool", "last", str(pair)], capture_output=True, text=True).stdout)
    assert last >= t0 + 80, "idle pair not refreshed"
    rows = fetch(pair, t0, last)

    def window(a, b):
        return [rows[t][1] for t in rows if t0 + a < t <= t0 + b]

    for v in window(4, 18) + window(53, 58):  # inside the on phases, clear of the edges
        assert v is not None and abs(v - rate) / rate < 0.15, (v, rate)
    for v in window(24, 46) + window(64, last - t0):  # idle: exactly zero, never unknown, nothing smeared
        assert v == 0.0, v

    # a pair that never carried traffic gets no file
    assert not (tmp_path / "ipv4/bytes/p2p/src-00005").exists()
    # VLAN 0: placed when both MACs are on one tag, dropped when they are not
    assert (tmp_path / "ipv4/bytes/p2p/src-00004/p2p.ipv4.bytes.src-00004.dst-00006.rrd").exists()
    assert not (tmp_path / "ipv4/bytes/p2p/src-00004/p2p.ipv4.bytes.src-00004.dst-00008.rrd").exists()
    assert "vlan-by-mac=" in flushes[-2] and "vlan-by-agent=" in flushes[-2]
    # ambiguous MAC: placed on the switch's tag
    assert (tmp_path / "ipv4/bytes/p2p/src-00009/p2p.ipv4.bytes.src-00009.dst-00003.rrd").exists()
    # the MAC stored as 02:00:00:00:00:07 in upper case still matched
    assert (tmp_path / "ipv4/bytes/p2p/src-00007/p2p.ipv4.bytes.src-00007.dst-00003.rrd").exists()
