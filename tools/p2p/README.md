# P2P graph diagnostics for IXP Manager

Tools for finding out why IXP Manager's member-to-member (P2P) graphs disagree with
reality, and fixing it. The full explanation of each failure mode, with references to
the IXP Manager source, is in [docs/p2p-graphs.md](../../docs/p2p-graphs.md).

| tool | where | what it answers |
|---|---|---|
| portal: IXP → Traffic → *P2P accuracy* | NetworkOps portal | Is sFlow recording all the traffic the ports carry? Too little (lost samples) or too much (double sampling)? |
| `collector-check.sh` | collector, root | Is the handler keeping up? Socket drops, flush duration, MAC-table API, disk, rrdcached delay, journal errors |
| `capture-and-audit.sh` → `sflow-audit.py` | collector, root | Which samples the handler throws away and why: unknown MACs (with switch/port), VLAN mismatches, core-link sampling, sampling precision, datagram loss |
| `pcap-dedupe.py` | collector | Drops datagrams `tcpdump -i any` captured more than once (bond/VLAN/bridge); used by `capture-and-audit.sh` |
| `rrd-check.py` | collector | Do the RRD files agree with each other? How far behind is disk? Which pair files carry no traffic (prune candidates)? |
| `sflow-to-rrd-handler` | collector | Drop-in replacement for IXP Manager's handler that never stops reading and writes only what carries traffic |

All read-only except the handler. Start with the portal card, then `collector-check.sh`.
