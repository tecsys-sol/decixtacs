#!/usr/bin/env python3
"""Audit a slice of sFlow traffic the way IXP Manager's sflow-to-rrd-handler sees it.

IXP Manager's P2P graphs come from tools/runtime/sflow/sflow-to-rrd-handler, which
reads ``sflowtool -l`` lines and keeps a sample only when its source AND destination
MAC are in IXP Manager's MAC table for the sample's VLAN tag. Everything else is
dropped without a trace unless the handler runs with --debug. This tool replays the
same decision on captured samples and says how much traffic is lost, why, and whose.

Input is what the handler reads, so the answer is about the real pipeline:

    tcpdump -i any -w /tmp/sflow.pcap -G 120 -W 1 udp port 6343      # does not disturb the handler
    sflowtool -r /tmp/sflow.pcap -l  > /tmp/sflow.lines               # what the handler parses
    sflowtool -r /tmp/sflow.pcap     > /tmp/sflow.full                # optional: sequence numbers
    curl -sH "X-IXP-Manager-API-Key: $KEY" $IXPM/api/v4/sflow-db-mapper/learned-macs > /tmp/macs.json
    sflow-audit.py --lines /tmp/sflow.lines --full /tmp/sflow.full --macs /tmp/macs.json --seconds 120

capture-and-audit.sh does all of that in one go. Python 3.6+, standard library only.
"""

import argparse
import json
import math
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

IPV4, IPV6 = "0x0800", "0x86dd"

# sflowtool -l columns, as indexed by sflow-to-rrd-handler:
# FLOW,agent,inputPort,outputPort,srcMAC,dstMAC,ethType,in_vlan,out_vlan,srcIP,dstIP,
# proto,tos,ttl,sport,dport,tcpFlags,pktSize,ipSize,samplingRate
F_AGENT, F_IN, F_OUT, F_SRC, F_DST, F_ETH, F_VLAN, F_SIZE, F_RATE = 1, 2, 3, 4, 5, 6, 7, 17, 19

REASONS = {
    "accepted": "counted in P2P graphs",
    "not_ip": "not IPv4/IPv6 (ARP, LLDP, ...) - the handler ignores it by design",
    "vlan_unknown": "VLAN tag not in IXP Manager's MAC table - every sample on it is dropped",
    "vlan_zero": "VLAN 0: the switch exports no VLAN for untagged frames - every sample is dropped",
    "dst_group": "destination is broadcast/multicast - not peer-to-peer, expected",
    "src_unknown": "source MAC not in IXP Manager for this VLAN - the sender's traffic is lost",
    "dst_unknown": "destination MAC not in IXP Manager for this VLAN - the receiver's traffic is lost",
    "same_vli": "source and destination map to the same VLAN interface",
}


def load_macs(src: str, api_key: Optional[str]) -> dict:
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"X-IXP-Manager-API-Key": api_key or ""})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    with open(src) as fh:
        return json.load(fh)


class MacTable:
    """IXP Manager's {infrastructure: {vlan tag: {mac: vli id}}}, looked up like the handler."""

    def __init__(self, raw: dict, infra: Optional[str] = None):
        if isinstance(raw, list):  # an empty table serialises as []
            raw = {}
        self.raw = {
            str(i): {str(t): {str(m): int(v) for m, v in macs.items()} for t, macs in tags.items()}
            for i, tags in raw.items()
            if infra is None or str(i) == str(infra)
        }
        self.tags = {t for tags in self.raw.values() for t in tags}
        self.vlis: Dict[int, Set[Tuple[str, str]]] = defaultdict(set)
        # every way a MAC could be written, to explain a near miss
        self.loose: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
        multi: Dict[Tuple[str, str], Set[int]] = defaultdict(set)
        for infra_id, tags in self.raw.items():
            for tag, macs in tags.items():
                for mac, vli in macs.items():
                    self.vlis[vli].add((tag, mac))
                    self.loose[normalise(mac)].append((infra_id, tag, vli))
                    multi[(tag, mac)].add(vli)
        # the handler walks infrastructures in hash order and takes the first hit
        self.ambiguous = {k: v for k, v in multi.items() if len(v) > 1}
        # MAC -> the one tag it is known on (None when on several), for samples without a VLAN
        tags_of: Dict[str, set] = defaultdict(set)
        for tags in self.raw.values():
            for tag, macs in tags.items():
                for mac in macs:
                    tags_of[mac].add(tag)
        self.mac2tag = {m: (next(iter(t)) if len(t) == 1 else None) for m, t in tags_of.items()}

    def tag_by_mac(self, src: str, dst: str) -> Optional[str]:
        """The improved handler's fallback: both MACs known on exactly one tag, the same one."""
        t = self.mac2tag.get(src)
        return t if t and t == self.mac2tag.get(dst) else None

    def get(self, tag: str, mac: str) -> int:
        for tags in self.raw.values():
            vli = tags.get(tag, {}).get(mac)
            if vli:
                return vli
        return 0

    def explain_miss(self, tag: str, mac: str) -> str:
        hits = self.loose.get(normalise(mac), [])
        if not hits:
            return "not in IXP Manager at all"
        exact_elsewhere = [h for h in hits if h[1] != tag and mac in self.raw[h[0]][h[1]]]
        if exact_elsewhere:
            _, other_tag, vli = exact_elsewhere[0]
            return f"known on VLAN tag {other_tag} (vli {vli}), not on {tag}"
        written = [m for h in hits for m in self.raw[h[0]][h[1]] if normalise(m) == normalise(mac)]
        return f"stored as {written[0]!r} - the handler matches exact lowercase hex only"


def normalise(mac: str) -> str:
    return re.sub(r"[^0-9a-f]", "", mac.lower())


def is_group(mac: str) -> bool:
    try:
        return bool(int(mac[:2], 16) & 1)
    except ValueError:
        return False


def classify(table: MacTable, eth: str, tag: str, src: str, dst: str) -> Tuple[str, int, int]:
    """The handler's decision for one sample, with the reason when it drops it."""
    if eth not in (IPV4, IPV6):
        return "not_ip", 0, 0
    if tag not in table.tags:
        return ("vlan_zero" if tag == "0" else "vlan_unknown"), 0, 0
    s, d = table.get(tag, src), table.get(tag, dst)
    if s and d:
        return ("same_vli" if s == d else "accepted"), s, d
    if not d and is_group(dst):
        return "dst_group", s, d
    if not s:
        return "src_unknown", s, d
    return "dst_unknown", s, d


class Audit:
    def __init__(self, table: MacTable, core_threshold: int):
        self.t = table
        self.core_threshold = core_threshold
        self.samples = 0
        self.bad_lines = 0
        self.reason_bytes: Counter = Counter()
        self.reason_samples: Counter = Counter()
        self.agent_samples: Counter = Counter()
        self.agent_bytes: Counter = Counter()
        self.agent_rates: Dict[str, Counter] = defaultdict(Counter)
        self.agent_vlan0: Counter = Counter()
        self.agent_eth: Dict[str, Counter] = defaultdict(Counter)
        self.unknown: Dict[Tuple[str, str, str], dict] = {}
        # (agent, input port) -> source VLI -> [samples, bytes]
        self.port_src: Dict[Tuple[str, str], Dict[int, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self.pair_samples: Counter = Counter()
        self.pair_bytes: Counter = Counter()
        self.by_mac_bytes = 0  # dropped for VLAN, placeable by MAC (improved handler)
        self.port_est: Counter = Counter()  # (agent, input port) -> sampled bytes, all samples

    def feed(self, line: str) -> None:
        if not line.startswith("FLOW"):
            return
        f = line.rstrip("\n").split(",")
        if len(f) < 20:
            self.bad_lines += 1
            return
        try:
            size, rate = int(f[F_SIZE]), int(f[F_RATE])
        except ValueError:
            self.bad_lines += 1
            return
        agent, inport, src, dst, eth, tag = f[F_AGENT], f[F_IN], f[F_SRC], f[F_DST], f[F_ETH], f[F_VLAN]
        est = size * rate
        self.samples += 1
        self.agent_samples[agent] += 1
        self.agent_bytes[agent] += est
        self.port_est[(agent, inport)] += est
        self.agent_rates[agent][rate] += 1
        self.agent_eth[agent][eth] += 1
        if tag == "0":
            self.agent_vlan0[agent] += 1

        reason, s, d = classify(self.t, eth, tag, src, dst)
        self.reason_samples[reason] += 1
        self.reason_bytes[reason] += est
        if reason in ("vlan_zero", "vlan_unknown"):
            t = self.t.tag_by_mac(src, dst)
            if t and classify(self.t, eth, t, src, dst)[0] == "accepted":
                self.by_mac_bytes += est

        if reason in ("src_unknown", "dst_unknown"):
            mac = src if reason == "src_unknown" else dst
            key = (reason, tag, mac)
            u = self.unknown.setdefault(key, {"samples": 0, "bytes": 0, "where": Counter()})
            u["samples"] += 1
            u["bytes"] += est
            if reason == "src_unknown":
                u["where"][f"{agent} port {inport}"] += 1
        if s and reason in ("accepted", "dst_unknown", "dst_group"):
            ps = self.port_src[(agent, inport)][s]
            ps[0] += 1
            ps[1] += est if reason == "accepted" else 0
        if reason == "accepted":
            self.pair_samples[(s, d)] += 1
            self.pair_bytes[(s, d)] += est

    # --- derived views ------------------------------------------------------------------

    def perimeter(self) -> dict:
        """Ports that see many senders are inter-switch links, or egress-sampled ports.

        The handler counts every sample it accepts, trusting that "the sflow accounting
        perimeter on the switches will ensure that each packet will be counted exactly
        once" - sFlow on member-facing ports, ingress only. A sample taken on a core link
        or on egress is the same packet counted a second time.
        """
        core_ports = []
        home: Dict[int, set] = defaultdict(set)
        for port, srcs in self.port_src.items():
            total = sum(v[0] for v in srcs.values())
            top_vli, (top_n, _) = max(srcs.items(), key=lambda kv: kv[1][0])
            if len(srcs) >= self.core_threshold and top_n < 0.8 * total:
                core_ports.append(
                    {
                        "agent": port[0],
                        "port": port[1],
                        "senders": len(srcs),
                        "samples": total,
                        "accepted_bytes": sum(v[1] for v in srcs.values()),
                    }
                )
            else:
                home[top_vli].add(port)
        core_keys = {(c["agent"], c["port"]) for c in core_ports}
        off_bytes = 0
        for port, srcs in self.port_src.items():
            if port in core_keys:
                off_bytes += sum(v[1] for v in srcs.values())
                continue
            for vli, (_, b) in srcs.items():
                if home.get(vli) and port not in home[vli]:
                    off_bytes += b
        core_ports.sort(key=lambda c: -c["accepted_bytes"])
        return {"core_ports": core_ports, "off_perimeter_bytes": off_bytes}

    def precision(self, seconds: Optional[float]) -> Optional[dict]:
        """How noisy the P2P graphs are at this sampling rate.

        A 5-minute RRD point built from n samples has a relative error of about
        +/-196/sqrt(n) % (95%). sFlow's own guidance; the sampling rate sets n.
        """
        if not seconds or not self.pair_samples:
            return None
        scale = 300.0 / seconds
        buckets = Counter()
        bytes_by = Counter()
        for pair, n in self.pair_samples.items():
            per5 = n * scale
            err = 196.0 / math.sqrt(per5)
            b = "<=10%" if err <= 10 else "<=20%" if err <= 20 else "<=50%" if err <= 50 else ">50%"
            buckets[b] += 1
            bytes_by[b] += self.pair_bytes[pair]
        total = sum(bytes_by.values()) or 1
        return {
            "pairs_seen": len(self.pair_samples),
            "pairs_by_error": dict(buckets),
            "traffic_share_by_error": {k: round(100.0 * v / total, 1) for k, v in bytes_by.items()},
        }

    def report(self, seconds: Optional[float], top: int) -> dict:
        total = sum(self.reason_bytes.values()) or 1
        lost = {
            k: v
            for k, v in self.reason_bytes.items()
            if k in ("vlan_unknown", "vlan_zero", "src_unknown", "dst_unknown", "same_vli")
        }
        unknown = sorted(self.unknown.items(), key=lambda kv: -kv[1]["bytes"])[:top]
        agents = []
        for a, n in self.agent_samples.most_common():
            rates = self.agent_rates[a]
            agents.append(
                {
                    "agent": a,
                    "samples": n,
                    "est_mbps": round(self.agent_bytes[a] * 8 / seconds / 1e6, 1) if seconds else None,
                    "sampling_rates": dict(rates.most_common(3)),
                    "vlan0_share": round(100.0 * self.agent_vlan0[a] / n, 1),
                    "non_ip_share": round(
                        100.0 * sum(c for e, c in self.agent_eth[a].items() if e not in (IPV4, IPV6)) / n, 1
                    ),
                }
            )
        per = self.perimeter()
        accepted = self.reason_bytes["accepted"] or 1
        return {
            "samples": self.samples,
            "unparsed_lines": self.bad_lines,
            "seconds": seconds,
            "mac_table": {
                "vlan_tags": sorted(self.t.tags),
                "vlan_interfaces": len(self.t.vlis),
                "ambiguous_entries": len(self.t.ambiguous),
            },
            "traffic_by_reason_pct": {k: round(100.0 * v / total, 2) for k, v in self.reason_bytes.most_common()},
            "lost_pct": round(100.0 * sum(lost.values()) / total, 2),
            "placeable_by_mac_pct": round(100.0 * self.by_mac_bytes / total, 2),
            "unknown_macs": [
                {
                    "reason": r,
                    "vlan": tag,
                    "mac": mac,
                    "samples": u["samples"],
                    "traffic_pct": round(100.0 * u["bytes"] / total, 2),
                    "est_mbps": round(u["bytes"] * 8 / seconds / 1e6, 2) if seconds else None,
                    "seen_on": [w for w, _ in u["where"].most_common(3)],
                    "why": self.t.explain_miss(tag, mac),
                }
                for (r, tag, mac), u in unknown
            ],
            "agents": agents,
            "double_counting": {
                "core_ports": per["core_ports"][:top],
                "off_perimeter_pct_of_accepted": round(100.0 * per["off_perimeter_bytes"] / accepted, 2),
            },
            "precision": self.precision(seconds),
        }


def sequence_loss(lines) -> dict:
    """Datagram and sample loss from full ``sflowtool`` output.

    packetSequenceNo counts datagrams per agent; sampleSequenceNo counts samples per
    data source. Gaps are datagrams lost between switch and capture point; dropEvents
    are samples the switch itself could not export (agent overload).
    """
    dgram: Dict[str, List[int]] = defaultdict(list)
    samp: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    drops: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    # (agent IP, ifIndex) -> [(switch uptime ms, ifInOctets)], from interface counter samples
    counters: Dict[Tuple[str, str], List[Tuple[int, int]]] = defaultdict(list)
    # (agent, sourceId) -> [(sampleSequenceNo, samplePool, meanSkipCount)], from flow samples
    pools: Dict[Tuple[str, str], List[Tuple[int, int, int]]] = defaultdict(list)
    # agent IP -> sampled bytes by where the sample was taken: on the port the packet came in
    # (ingress), on the port it left by (egress), or neither
    direction: Dict[str, Counter] = defaultdict(Counter)
    agent = sub = ip = None
    uptime = None
    smp: Dict[str, str] = {}
    for raw in lines:
        parts = raw.split(None, 1)
        if not parts:
            continue
        k = parts[0]
        v = parts[1].strip() if len(parts) > 1 else ""
        # sflowtool writes "startSample ------" / "endSample   ------": the dashes are not a value
        if k == "startSample":
            smp = {}
        elif k == "endSample":
            st = smp.get("sampleType")
            src, seq = smp.get("sourceId"), smp.get("sampleSequenceNo")
            if st == "FLOWSAMPLE" and agent and src and seq:
                samp[(agent, src)].append(int(seq))
                if "dropEvents" in smp:
                    drops[(agent, src)].append(int(smp["dropEvents"]))
                if "samplePool" in smp and "meanSkipCount" in smp:
                    pools[(agent, src)].append((int(seq), int(smp["samplePool"]), int(smp["meanSkipCount"])))
                if ip and "sampledPacketSize" in smp and "meanSkipCount" in smp:
                    port = src.split(":")[-1]
                    where = (
                        "ingress"
                        if port == smp.get("inputPort")
                        else "egress"
                        if port == smp.get("outputPort")
                        else "other"
                    )
                    direction[ip][where] += int(smp["sampledPacketSize"]) * int(smp["meanSkipCount"])
            elif st == "COUNTERSSAMPLE" and ip and uptime is not None and "ifIndex" in smp and "ifInOctets" in smp:
                counters[(ip, smp["ifIndex"])].append((uptime, int(smp["ifInOctets"])))
            smp = {}
        elif k == "startDatagram":
            agent = sub = ip = None
            uptime = None
        elif k == "agentSubId":
            sub = v
        elif k == "agent":
            ip = v
            agent = v + (f"/{sub}" if sub not in (None, "0") else "")
        elif k == "packetSequenceNo" and agent:
            dgram[agent].append(int(v))
        elif k == "sysUpTime":
            uptime = int(v)
        elif k in (
            "sampleType",
            "sourceId",
            "sampleSequenceNo",
            "dropEvents",
            "samplePool",
            "meanSkipCount",
            "ifIndex",
            "ifInOctets",
            "inputPort",
            "outputPort",
            "sampledPacketSize",
        ):
            smp.setdefault(k, v)

    def gaps(seqs: List[int]) -> Tuple[int, int]:
        """(expected, missing), restarting the count where the sequence resets."""
        exp = miss = 0
        seg = [seqs[0]] if seqs else []
        for a in seqs[1:]:
            if a < seg[-1] - 1000:  # agent restart or 32-bit wrap
                e, m = _span(seg)
                exp, miss = exp + e, miss + m
                seg = [a]
            else:
                seg.append(a)
        if seg:
            e, m = _span(seg)
            exp, miss = exp + e, miss + m
        return exp, miss

    out = {"agents": []}
    for a, seqs in sorted(dgram.items()):
        exp, miss = gaps(seqs)
        srcs = [k for k in samp if k[0] == a]
        s_exp = s_miss = 0
        for k in srcs:
            e, m = gaps(samp[k])
            s_exp, s_miss = s_exp + e, s_miss + m
        d = sum(max(v) - min(v) for k, v in drops.items() if k[0] == a and v)
        out["agents"].append(
            {
                "agent": a,
                "datagrams": len(seqs),
                # the same datagram captured more than once (tcpdump -i any over a bond/VLAN/bridge)
                "duplicate_pct": round(100.0 * (len(seqs) - len(set(seqs))) / len(seqs), 1) if seqs else 0.0,
                "datagram_loss_pct": round(100.0 * miss / exp, 2) if exp else 0.0,
                "flow_sample_loss_pct": round(100.0 * s_miss / s_exp, 2) if s_exp else 0.0,
                "agent_drop_events": d,
            }
        )
    out["counters"] = {k: r for k, r in ((k, _counter_rate(v)) for k, v in counters.items()) if r is not None}
    out["effective_rates"] = _effective_rates(pools)
    out["sampling_direction"] = [
        {"agent": ip, **{k: round(100.0 * c[k] / sum(c.values()), 1) for k in ("ingress", "egress", "other")}}
        for ip, c in sorted(direction.items())
        if sum(c.values())
    ]
    return out


def _counter_rate(obs: List[Tuple[int, int]]) -> Optional[float]:
    """Bytes/s from successive ifInOctets readings, timed by the switch's own uptime."""
    obs = sorted(set(obs))
    total = secs = 0.0
    for (t0, o0), (t1, o1) in zip(obs, obs[1:]):
        if t1 > t0 and o1 >= o0:  # a counter that went backwards was reset: skip that step
            total += o1 - o0
            secs += (t1 - t0) / 1000.0
    return total / secs if secs >= 10 else None


def _effective_rates(pools) -> List[dict]:
    """Per agent: packets the samplers saw (samplePool) per sample they generated, against the
    sampling rate they report. A higher effective rate means each sample stands for more traffic
    than the switch says, and every estimate - P2P graphs included - comes out too low."""
    per: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # pool delta, seq delta, reported x seq
    for (agent, _src), obs in pools.items():
        obs = sorted(set(obs))
        for (s0, p0, _), (s1, p1, k1) in zip(obs, obs[1:]):
            ds = (s1 - s0) % 2**32
            dp = (p1 - p0) % 2**32
            if 0 < ds < 10**6:
                a = per[agent.split("/")[0]]
                a[0] += dp
                a[1] += ds
                a[2] += k1 * ds
    out = []
    for agent, (dp, ds, rs) in sorted(per.items()):
        if ds:
            out.append({"agent": agent, "reported_rate": round(rs / ds), "effective_rate": round(dp / ds)})
    return out


def _span(seg: List[int]) -> Tuple[int, int]:
    uniq = sorted(set(seg))
    expected = uniq[-1] - uniq[0] + 1
    return expected, expected - len(uniq)


def sampling_vs_counters(audit: "Audit", loss: dict, seconds: Optional[float], unsampled_bps: float = 1e8) -> dict:
    """How much of each switch's ingress traffic its samples account for.

    A port's own ifInOctets counter (from sFlow counter samples) is the truth. The samples
    taken on that port, scaled by their sampling rate, should add up to it. Ports with
    traffic and no samples at all are either member ports where sampling is off - their
    traffic is missing from every P2P graph - or core links, which correctly are not sampled.
    """
    if not seconds or not loss or not loss.get("counters"):
        return {}
    counters = loss["counters"]
    agents: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    unsampled = []
    for (ip, ifindex), rate in counters.items():
        est = audit.port_est.get((ip, ifindex), 0) / seconds
        if est > 0:
            a = agents[ip]
            a[0] += rate
            a[1] += est
            a[2] += 1
        elif rate * 8 >= unsampled_bps:
            unsampled.append({"agent": ip, "ifindex": ifindex, "mbps": round(rate * 8 / 1e6, 1)})
    per_agent = [
        {
            "agent": ip,
            "ports": int(n),
            "counter_mbps": round(c * 8 / 1e6, 1),
            "sampled_mbps": round(e * 8 / 1e6, 1),
            "ratio": round(e / c, 3) if c else None,
        }
        for ip, (c, e, n) in sorted(agents.items())
    ]
    tc = sum(a[0] for a in agents.values())
    te = sum(a[1] for a in agents.values())
    unsampled.sort(key=lambda u: -u["mbps"])
    return {
        "per_agent": per_agent,
        "overall_ratio": round(te / tc, 3) if tc else None,
        "unsampled_ports": unsampled,
        "unsampled_mbps": round(sum(u["mbps"] for u in unsampled), 1),
    }


def print_text(r: dict, loss: Optional[dict]) -> None:
    w = sys.stdout.write
    secs = f" over {r['seconds']:.0f}s" if r["seconds"] else ""
    w(f"\n== Samples{secs}: {r['samples']}  (unparsed lines: {r['unparsed_lines']})\n")
    mt = r["mac_table"]
    w(f"   MAC table: {mt['vlan_interfaces']} VLAN interfaces on VLAN tags {', '.join(mt['vlan_tags']) or '(none)'}")
    w(
        f"; {mt['ambiguous_entries']} MAC/VLAN entries map to more than one interface\n"
        if mt["ambiguous_entries"]
        else "\n"
    )

    w("\n== What the handler does with the traffic (share of estimated bytes)\n")
    for k, v in r["traffic_by_reason_pct"].items():
        w(f"   {v:6.2f}%  {k:13s} {REASONS[k]}\n")
    w(f"   => {r['lost_pct']:.2f}% of peering traffic never reaches a P2P graph\n")
    if r.get("placeable_by_mac_pct"):
        pct = r["placeable_by_mac_pct"]
        w(f"   => {pct:.2f}% has no usable VLAN but both MACs are known on one tag: the improved\n")
        w("      handler (tools/p2p/sflow-to-rrd-handler) places it there instead of dropping it\n")

    if r["unknown_macs"]:
        w("\n== MACs the handler cannot place (largest first)\n")
        for u in r["unknown_macs"]:
            mbps = f"{u['est_mbps']:8.2f} Mb/s" if u["est_mbps"] is not None else f"{u['traffic_pct']:6.2f}%"
            where = f"  on {', '.join(u['seen_on'])}" if u["seen_on"] else ""
            w(f"   {u['reason']:11s} vlan {u['vlan']:>5s}  {u['mac']}  {mbps}  - {u['why']}{where}\n")

    w("\n== Agents (switches) exporting sFlow\n")
    for a in r["agents"]:
        rates = ", ".join(f"1:{k}" for k in a["sampling_rates"])
        mbps = f"{a['est_mbps']:9.1f} Mb/s" if a["est_mbps"] is not None else ""
        flag = "  <- VLAN missing, all dropped" if a["vlan0_share"] > 50 else ""
        w(f"   {a['agent']:16s} {a['samples']:8d} samples {mbps}  rate {rates}  vlan0 {a['vlan0_share']}%{flag}\n")

    dc = r["double_counting"]
    w("\n== Double counting (sFlow outside the member-facing ingress perimeter)\n")
    if dc["core_ports"]:
        for c in dc["core_ports"]:
            w(
                f"   {c['agent']} port {c['port']}: {c['senders']} different members send through it "
                f"({c['samples']} samples) - looks like a core/trunk link with sFlow enabled\n"
            )
    else:
        w("   no input port carries many members' traffic - no sign of core-link sampling\n")
    w(f"   {dc['off_perimeter_pct_of_accepted']:.2f}% of counted traffic was sampled away from the sender's own port\n")

    p = r["precision"]
    if p:
        w("\n== Statistical precision of 5-minute P2P points at the current sampling rate\n")
        for k in ("<=10%", "<=20%", "<=50%", ">50%"):
            if k in p["pairs_by_error"]:
                pairs, share = p["pairs_by_error"][k], p["traffic_share_by_error"][k]
                w(f"   error {k:>6s}: {pairs:6d} member pairs, {share:5.1f}% of traffic\n")

    cmpc = r.get("sampling_vs_counters") or {}
    if cmpc:
        w("\n== Do the samples account for the traffic? (sampled estimate vs the ports' own ifInOctets)\n")
        for a in cmpc["per_agent"]:
            flag = "  <- under-sampled" if a["ratio"] is not None and a["ratio"] < 0.8 else ""
            w(
                f"   {a['agent']:16s} {a['ports']:4d} sampled ports: counters {a['counter_mbps']:10.1f} Mb/s, "
                f"samples {a['sampled_mbps']:10.1f} Mb/s  = {100 * (a['ratio'] or 0):5.1f}%{flag}\n"
            )
        if cmpc["overall_ratio"] is not None:
            pct = 100 * cmpc["overall_ratio"]
            w(f"   => on the ports that are sampled, samples account for {pct:.1f}% of the traffic\n")
        if cmpc["unsampled_ports"]:
            w(
                f"   {len(cmpc['unsampled_ports'])} port(s) carry traffic but sent no flow samples "
                f"({cmpc['unsampled_mbps']:.0f} Mb/s in total). Member ports among them are missing from P2P\n"
                "   graphs entirely; core links are correctly not sampled. Look the ifIndex up in IXP Manager:\n"
            )
            for u in cmpc["unsampled_ports"][:15]:
                w(f"     {u['agent']:16s} ifIndex {u['ifindex']:>6s}  {u['mbps']:10.1f} Mb/s\n")
    dirs = (loss or {}).get("sampling_direction") or []
    if dirs:
        w("\n== Where each switch samples (share of sampled traffic)\n")
        for d in dirs:
            flag = "  <- egress sampling: these packets are counted again where they entered" if d["egress"] > 5 else ""
            w(f"   {d['agent']:16s} ingress {d['ingress']:5.1f}%  egress {d['egress']:5.1f}%  other {d['other']:5.1f}%")
            w(flag + "\n")
    rates = (loss or {}).get("effective_rates") or []
    if rates:
        w("\n== Sampling rate: reported by the switch vs effective (packets seen per sample)\n")
        for e in rates:
            off = e["effective_rate"] / e["reported_rate"] if e["reported_rate"] else 0
            flag = f"  <- each sample stands for {off:.1f}x the reported rate" if off > 1.2 else ""
            w(f"   {e['agent']:16s} reported 1:{e['reported_rate']:<8d} effective 1:{e['effective_rate']:<8d}{flag}\n")

    dup = [a for a in (loss or {}).get("agents", []) if a.get("duplicate_pct")]
    if dup:
        w("\n!! The capture holds duplicate datagrams - every figure from these switches is inflated:\n")
        for a in dup:
            w(f"   {a['agent']:16s} {a['duplicate_pct']:5.1f}% of its datagrams were captured more than once\n")
        w("   Re-capture with capture-and-audit.sh, which drops duplicates (pcap-dedupe.py).\n")

    if loss:
        w("\n== Loss before the handler (from sequence numbers)\n")
        for a in loss["agents"]:
            flag = "  <- loss" if a["datagram_loss_pct"] > 0.5 or a["agent_drop_events"] else ""
            w(
                f"   {a['agent']:16s} datagrams {a['datagrams']:7d}  lost {a['datagram_loss_pct']:5.2f}%  "
                f"flow samples lost {a['flow_sample_loss_pct']:5.2f}%  "
                f"switch drop events {a['agent_drop_events']}{flag}\n"
            )
    w("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lines", required=True, help="sflowtool -l output ('-' for stdin)")
    ap.add_argument("--macs", required=True, help="learned-macs / configured-macs JSON file or API URL")
    ap.add_argument("--api-key", help="IXP Manager API key when --macs is a URL")
    ap.add_argument("--full", help="full sflowtool output of the same capture, for loss figures")
    ap.add_argument("--seconds", type=float, help="capture length, for rates and precision")
    ap.add_argument("--infraid", help="restrict to one infrastructure, as the handler's --infraid")
    ap.add_argument(
        "--core-threshold",
        type=int,
        default=4,
        help="distinct senders on one input port that mark it as a core link (default 4)",
    )
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    table = MacTable(load_macs(a.macs, a.api_key), a.infraid)
    audit = Audit(table, a.core_threshold)
    fh = sys.stdin if a.lines == "-" else open(a.lines, errors="replace")
    for line in fh:
        audit.feed(line)
    loss = None
    if a.full:
        with open(a.full, errors="replace") as ff:
            loss = sequence_loss(ff)
    r = audit.report(a.seconds, a.top)
    r["sampling_vs_counters"] = sampling_vs_counters(audit, loss, a.seconds)
    if loss:
        # tuple keys are for the computation only
        loss = {k: v for k, v in loss.items() if k != "counters"}
    if a.json:
        json.dump({"audit": r, "loss": loss}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_text(r, loss)
    return 0 if audit.samples else 2


if __name__ == "__main__":
    sys.exit(main())
