import importlib.util
import pathlib
import shutil
import subprocess
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rrd_check", HERE.parent / "rrd-check.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

pytestmark = pytest.mark.skipif(shutil.which("rrdtool") is None, reason="needs rrdtool")
STEP = 10


def make(path: pathlib.Path, start: int, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rrdtool",
            "create",
            str(path),
            "--step",
            str(STEP),
            "--start",
            str(start - STEP),
            "DS:traffic_in:GAUGE:600:U:U",
            "DS:traffic_out:GAUGE:600:U:U",
            "RRA:AVERAGE:0.5:1:500",
            "RRA:MAX:0.5:1:500",
        ],
        check=True,
    )
    if values:
        subprocess.run(
            ["rrdtool", "update", str(path), *[f"{start + k * STEP}:{i}:{o}" for k, (i, o) in enumerate(values)]],
            check=True,
        )


@pytest.fixture
def base(tmp_path):
    now = int(time.time()) // STEP * STEP - 30 * STEP

    def p(s, d):
        return pathlib.Path(rc.p2p_path(str(tmp_path), 4, "bytes", s, d))

    # 1<->2 consistent, 1<->3 written far apart (B's out is a different series)
    make(p(1, 2), now, [(100, 200)] * 20)
    make(p(2, 1), now, [(200, 100)] * 20)
    make(p(1, 3), now, [(50, 0)] * 20)
    make(p(3, 1), now, [(0, 10)] * 20)
    make(pathlib.Path(rc.ind_path(str(tmp_path), 4, "bytes", 1)), now, [(150, 200)] * 20)
    make(p(1, 4), now, [(0, 0)] * 20)  # idle: known zeros
    make(p(1, 5), now, [])  # no data at all: not idle
    return tmp_path


def test_pair_symmetry(base, capsys):
    assert rc.main(["--base", str(base), "--daemon", "", "pair", "1", "2", "--days", "0.05"]) == 1  # no IPv6 files
    out = capsys.readouterr().out
    assert "differ by median 0.00%, p95 0.00%" in out
    rc.main(["--base", str(base), "--daemon", "", "pair", "1", "3", "--days", "0.05"])
    assert "flushes are taking too long" in capsys.readouterr().out


def test_sum_against_individual(base, capsys):
    # P2P "in" adds up to 150 (100 + 50 + 0 + 0) and "out" to 200: matches the individual file
    assert rc.main(["--base", str(base), "--daemon", "", "sum", "1", "--days", "0.05"]) == 0
    assert "sent 1.000, received 1.000" in capsys.readouterr().out


def test_idle_skips_files_without_data(base, capsys):
    rc.main(["--base", str(base), "--daemon", "", "idle", "--days", "0.05"])
    listed = capsys.readouterr().out.split()
    assert [pathlib.Path(x).name for x in listed] == ["p2p.ipv4.bytes.src-00001.dst-00004.rrd"]
