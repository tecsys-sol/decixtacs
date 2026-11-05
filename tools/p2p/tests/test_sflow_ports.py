import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sflow_ports", HERE.parent / "sflow-ports.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

HEAD = "switch\thostname\tipv4addr\tloopback_ip\tifindex\tifname\tport\tporttype\tpistatus\tcustomer"
ROWS = [
    # sw1: two connected member ports, a disconnected one, a core link
    "sw1\tsw1.ix\t172.17.138.11\tNULL\t501\txe-0/0/1\tx1\t1\t1\tAlpha",
    "sw1\tsw1.ix\t172.17.138.11\tNULL\t502\txe-0/0/2\tx2\t1\t1\tBeta",
    "sw1\tsw1.ix\t172.17.138.11\tNULL\t503\txe-0/0/3\tx3\t1\t3\tGamma",
    "sw1\tsw1.ix\t172.17.138.11\tNULL\t600\tet-0/0/48\tc1\t3\tNULL\tNULL",
    # sw2: a member port, but the switch sends nothing
    "sw2\tsw2.ix\t172.17.140.4\tNULL\t501\txe-0/0/1\tx1\t1\t1\tDelta",
]


def capture():
    def dg(agent, samples):
        out = ["startDatagram =================================", f"agent {agent}"]
        for s in samples:
            out += ["startSample ----------------------", *s, "endSample   ----------------------"]
        return out

    ctr = lambda i: ["sampleType COUNTERSSAMPLE", f"sourceId 0:{i}", f"ifIndex {i}"]  # noqa: E731
    flw = lambda i, r: ["sampleType FLOWSAMPLE", f"sourceId 0:{i}", f"meanSkipCount {r}"]  # noqa: E731
    lines = dg("172.17.138.11", [ctr(501), flw(501, 20000), flw(501, 160000), ctr(600)])
    lines += dg("172.17.99.9", [ctr(1)])
    return [ln + "\n" for ln in lines]


def test_report(tmp_path):
    p = tmp_path / "ports.tsv"
    p.write_text("\n".join([HEAD, *ROWS]) + "\n")
    enabled, rates = sp.parse_capture(capture())
    text, summary = sp.report(sp.load_ports(str(p)), enabled, rates, 20000, resolve=False)
    assert "set protocols sflow interfaces xe-0/0/2    # Beta (ifIndex 502)" in text
    assert "xe-0/0/3" not in text  # not connected: not a member port to sample
    assert "delete protocols sflow interfaces xe-0/0/1 sample-rate    # reported 1:20000 x1, 1:160000 x1" in text
    assert "delete protocols sflow interfaces et-0/0/48    # core (ifIndex 600)" in text
    assert "## sw2: 1 member ports - NO sFlow from this switch reaches the collector" in text
    assert "172.17.99.9" in text
    sw1 = next(s for s in summary["switches"] if s["switch"] == "sw1")
    assert (sw1["members"], sw1["missing"], sw1["wrong_rate"], sw1["sampled_core_links"]) == (2, 1, 1, 1)


def test_print_sql(capsys):
    assert sp.main(["--print-sql"]) == 0
    assert "sp.ifIndex AS ifindex" in capsys.readouterr().out
