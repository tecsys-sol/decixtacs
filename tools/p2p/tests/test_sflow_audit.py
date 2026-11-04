import importlib.util
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sflow_audit", HERE.parent / "sflow-audit.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

# infrastructure 1, peering VLAN tag 100; vli 11/12/13 are three members
MACS = {"1": {"100": {"0000000000a1": 11, "0000000000b2": 12, "0000000000c3": 13, "AABBCCDDEEFF": 14}}}


def flow(agent="10.0.0.1", inp=5, src="0000000000a1", dst="0000000000b2", eth="0x0800", vlan=100, size=1000, rate=1000):
    return (
        f"FLOW,{agent},{inp},9,{src},{dst},{eth},{vlan},{vlan},192.0.2.1,192.0.2.2,6,0x00,64,1,2,0x10,"
        f"{size},{size - 18},{rate}\n"
    )


def run(lines, seconds=60.0, macs=MACS):
    a = sa.Audit(sa.MacTable(macs), core_threshold=3)
    for ln in lines:
        a.feed(ln)
    return a.report(seconds, top=10)


def test_drop_reasons_follow_the_handler():
    r = run(
        [
            flow(),  # accepted
            flow(eth="0x0806"),  # ARP
            flow(vlan=200),  # tag not in the table
            flow(vlan=0),  # switch exports no VLAN
            flow(dst="ffffffffffff"),  # broadcast
            flow(src="0000000000ff"),  # unknown sender
            flow(dst="0000000000ee"),  # unknown receiver
            flow(src="0000000000a1", dst="0000000000a1"),  # same interface
        ]
    )
    assert r["samples"] == 8
    assert set(r["traffic_by_reason_pct"]) == set(sa.REASONS)
    assert all(v == 12.5 for v in r["traffic_by_reason_pct"].values())
    # vlan_unknown, vlan_zero, src_unknown, dst_unknown, same_vli
    assert r["lost_pct"] == 62.5


def test_near_misses_are_explained():
    r = run(
        [
            flow(src="aabbccddeeff"),
            flow(src="0000000000c3", vlan=100, dst="0000000000d4"),
            flow(src="0000000000a1", dst="0000000000b2", vlan=300),
        ],
        macs={"1": {"100": {"AABBCCDDEEFF": 14, "0000000000c3": 13, "0000000000b2": 12}, "300": {"0000000000a1": 11}}},
    )
    why = {u["mac"]: u["why"] for u in r["unknown_macs"]}
    assert "stored as 'AABBCCDDEEFF'" in why["aabbccddeeff"]
    assert why["0000000000d4"] == "not in IXP Manager at all"
    # sender known on 300; the receiver only on 100 - a member on the wrong tag in IXP Manager
    assert why["0000000000b2"] == "known on VLAN tag 100 (vli 12), not on 300"


def test_core_link_sampling_is_flagged_as_double_counting():
    lines = []
    # member-facing ports: one sender each
    lines += [flow(inp=1, src="0000000000a1", dst="0000000000b2")] * 10
    lines += [flow(inp=2, src="0000000000b2", dst="0000000000a1")] * 10
    lines += [flow(inp=3, src="0000000000c3", dst="0000000000a1")] * 10
    # the same traffic seen again on an inter-switch link of another switch
    lines += [
        flow(agent="10.0.0.2", inp=49, src=s, dst="0000000000a1")
        for s in ("0000000000b2", "0000000000c3", "0000000000b2", "0000000000c3")
    ]
    lines += [flow(agent="10.0.0.2", inp=49, src="0000000000a1", dst="0000000000b2")] * 2
    r = run(lines)
    core = r["double_counting"]["core_ports"]
    assert [(c["agent"], c["port"], c["senders"]) for c in core] == [("10.0.0.2", "49", 3)]
    assert r["double_counting"]["off_perimeter_pct_of_accepted"] == round(100 * 6 / 36, 2)


def test_vlan0_agent_and_precision():
    r = run([flow(agent="10.0.0.9", vlan=0)] * 3 + [flow()] * 100, seconds=60)
    agents = {a["agent"]: a for a in r["agents"]}
    assert agents["10.0.0.9"]["vlan0_share"] == 100.0
    p = r["precision"]
    # 100 samples/min -> 500 per 5 min -> +/-8.8%
    assert p["pairs_by_error"] == {"<=10%": 1}


def test_sequence_loss_from_full_output():
    text = []
    for seq in (1, 2, 4, 5):  # datagram 3 lost
        text += [
            "startDatagram =================================",
            "agent 10.0.0.1",
            f"packetSequenceNo {seq}",
            "startSample ----------------------",
            "sampleType FLOWSAMPLE",
            f"sampleSequenceNo {seq * 2}",
            "sourceId 0:5",
            f"dropEvents {seq * 10}",
            "endSample   ----------------------",
            "endDatagram   =================================",
        ]
    out = sa.sequence_loss(t + "\n" for t in text)
    a = out["agents"][0]
    assert a["datagrams"] == 4 and a["datagram_loss_pct"] == 20.0
    assert a["agent_drop_events"] == 40


def test_cli_json(tmp_path, capsys):
    (tmp_path / "macs.json").write_text(json.dumps(MACS))
    (tmp_path / "lines").write_text(flow() * 5)
    assert (
        sa.main(
            ["--lines", str(tmp_path / "lines"), "--macs", str(tmp_path / "macs.json"), "--json", "--seconds", "10"]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["audit"]["traffic_by_reason_pct"] == {"accepted": 100.0}
    # empty table as IXP Manager serialises it
    (tmp_path / "empty.json").write_text("[]")
    assert sa.main(["--lines", str(tmp_path / "lines"), "--macs", str(tmp_path / "empty.json")]) == 0
