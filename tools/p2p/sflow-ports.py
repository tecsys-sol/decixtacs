#!/usr/bin/env python3
"""Which member ports have no sFlow, which sample at the wrong rate, and which core links are
sampled - per switch, as Junos commands.

IXP Manager knows every member port (switchport type peering/reseller with a connected
physical interface) and its SNMP ifIndex. A capture of the collector's sFlow shows which
ports are sFlow-enabled: Junos sends a counter sample for every sFlow interface about every
20 seconds, traffic or not, and every flow sample carries the rate it was taken at.

Step 1, where IXP Manager's database is reachable (read-only):

    sflow-ports.py --print-sql > ports.sql
    mysql -h <db-host> -u <ro-user> -p ixpmanager -B < ports.sql > ports.tsv

Step 2, on the collector, against a capture (capture-and-audit.sh keeps it in /tmp/p2p-audit.*):

    sflow-ports.py --ports ports.tsv --full /tmp/p2p-audit.XXXX/sflow.full

Prints, per switch, `set protocols sflow interfaces ...` for member ports without sFlow,
the ports whose samples report another rate than --rate, and `delete ...` for core links
that are sampled. Review before committing. Python 3.6+, standard library only.
"""

import argparse
import csv
import socket
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple

SQL = """-- IXP Manager 7.x: every switch port with its SNMP ifIndex and what is connected to it
SELECT s.name AS switch, s.hostname, s.ipv4addr, s.loopback_ip,
       sp.ifIndex AS ifindex, sp.ifName AS ifname, sp.name AS port, sp.type AS porttype,
       pi.status AS pistatus, c.name AS customer
FROM switchport sp
JOIN switch s ON s.id = sp.switchid
LEFT JOIN physicalinterface pi ON pi.switchportid = sp.id
LEFT JOIN virtualinterface vi ON vi.id = pi.virtualinterfaceid
LEFT JOIN cust c ON c.id = vi.custid
WHERE s.active = 1 AND sp.ifIndex IS NOT NULL
ORDER BY s.name, sp.ifIndex;
"""

PEERING, CORE, RESELLER = "1", "3", "7"
CONNECTED = "1"


def load_ports(path: str) -> List[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for r in rows:
        for k, v in r.items():
            if v in ("NULL", None):
                r[k] = ""
    return rows


def parse_capture(lines) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], Counter]]:
    """agent IP -> sFlow-enabled ifIndexes; (agent IP, ifIndex) -> reported sampling rates."""
    enabled: Dict[str, Set[str]] = defaultdict(set)
    rates: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    ip = None
    smp: Dict[str, str] = {}
    for raw in lines:
        parts = raw.split(None, 1)
        if not parts:
            continue
        k = parts[0]
        v = parts[1].strip() if len(parts) > 1 else ""
        if k == "startDatagram":
            ip = None
        elif k == "agent":
            ip = v
        elif k == "startSample":
            smp = {}
        elif k == "endSample":
            st = smp.get("sampleType")
            if ip and st == "COUNTERSSAMPLE" and smp.get("ifIndex"):
                enabled[ip].add(smp["ifIndex"])
            elif ip and st == "FLOWSAMPLE" and smp.get("sourceId"):
                port = smp["sourceId"].split(":")[-1]
                enabled[ip].add(port)
                if smp.get("meanSkipCount"):
                    rates[(ip, port)][int(smp["meanSkipCount"])] += 1
            smp = {}
        elif k in ("sampleType", "sourceId", "ifIndex", "meanSkipCount"):
            smp.setdefault(k, v)
    return enabled, rates


def match_agents(ports: List[dict], agents: Set[str], resolve: bool) -> Dict[str, str]:
    """switch name -> the agent address its sFlow comes from (management or loopback address)."""
    out = {}
    for sw in {r["switch"] for r in ports}:
        rows = [r for r in ports if r["switch"] == sw]
        cands = {rows[0]["ipv4addr"], rows[0]["loopback_ip"]} - {""}
        if resolve and rows[0]["hostname"]:
            try:
                cands.add(socket.gethostbyname(rows[0]["hostname"]))
            except OSError:
                pass
        hit = sorted(cands & agents)
        if hit:
            out[sw] = hit[0]
    return out


def name(r: dict) -> str:
    return r["ifname"] or r["port"]


def report(ports: List[dict], enabled, rates, rate: int, resolve: bool = True) -> Tuple[str, dict]:
    agents = set(enabled)
    sw_agent = match_agents(ports, agents, resolve)
    by_switch: Dict[str, List[dict]] = defaultdict(list)
    for r in ports:
        by_switch[r["switch"]].append(r)

    out: List[str] = []
    summary = {"switches": [], "unmatched_agents": sorted(agents - set(sw_agent.values()))}
    for sw in sorted(by_switch):
        rows = by_switch[sw]
        members = [r for r in rows if r["porttype"] in (PEERING, RESELLER) and r["pistatus"] == CONNECTED]
        cores = [r for r in rows if r["porttype"] == CORE]
        agent = sw_agent.get(sw)
        if not members and not cores:
            continue
        if agent is None:
            if members:
                out.append(f"\n## {sw}: {len(members)} member ports - NO sFlow from this switch reaches the collector")
                out.append("#  (or its agent address is neither its management nor loopback IP in IXP Manager)")
                summary["switches"].append(
                    {"switch": sw, "agent": None, "members": len(members), "missing": len(members)}
                )
            continue
        on = enabled[agent]
        missing = [r for r in members if r["ifindex"] not in on]
        wrong = []
        for r in members:
            seen = rates.get((agent, r["ifindex"]))
            if seen:
                off = {k: n for k, n in seen.items() if k != rate}
                if off:
                    wrong.append((r, seen))
        sampled_cores = [r for r in cores if r["ifindex"] in on]
        summary["switches"].append(
            {
                "switch": sw,
                "agent": agent,
                "members": len(members),
                "missing": len(missing),
                "wrong_rate": len(wrong),
                "sampled_core_links": len(sampled_cores),
            }
        )
        out.append(
            f"\n## {sw} ({agent}): {len(members)} member ports, {len(members) - len(missing)} with sFlow, "
            f"{len(missing)} without"
        )
        if missing:
            out.append("# member ports without sFlow:")
            for r in missing:
                out.append(
                    f"set protocols sflow interfaces {name(r)}    # {r['customer'] or '?'} (ifIndex {r['ifindex']})"
                )
        if wrong:
            out.append(f"# member ports whose samples report another rate than 1:{rate} - remove any per-port rate,")
            out.append("# then check 'show sflow interface' for an adapted rate (adaptive sampling):")
            for r, seen in wrong:
                got = ", ".join(f"1:{k} x{n}" for k, n in seen.most_common(3))
                out.append(f"delete protocols sflow interfaces {name(r)} sample-rate    # reported {got}")
        if sampled_cores:
            out.append("# core / inter-switch links with sFlow - sampled traffic there is counted twice:")
            for r in sampled_cores:
                out.append(f"delete protocols sflow interfaces {name(r)}    # core (ifIndex {r['ifindex']})")
    if summary["unmatched_agents"]:
        out.append(
            "\n## sFlow agents not matched to any IXP Manager switch (management/loopback IP): "
            + ", ".join(summary["unmatched_agents"])
        )
    return "\n".join(out).lstrip("\n") + "\n", summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--print-sql", action="store_true", help="print the read-only query for IXP Manager's database")
    ap.add_argument("--ports", help="tab-separated output of that query (mysql -B)")
    ap.add_argument("--full", help="full sflowtool output of a capture (sflow.full)")
    ap.add_argument("--rate", type=int, default=20000, help="the sampling rate every member port should use")
    ap.add_argument("--no-resolve", action="store_true", help="do not resolve switch hostnames to match agents")
    a = ap.parse_args(argv)
    if a.print_sql:
        sys.stdout.write(SQL)
        return 0
    if not (a.ports and a.full):
        ap.error("--ports and --full are required (or --print-sql)")
    ports = load_ports(a.ports)
    with open(a.full, errors="replace") as fh:
        enabled, rates = parse_capture(fh)
    text, _ = report(ports, enabled, rates, a.rate, resolve=not a.no_resolve)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
