# IXP Manager P2P graphs: why they read wrong, and how to find out which reason applies

Members see a P2P graph per peer in IXP Manager (Statistics → P2P). When those graphs
disagree with what members see on their own routers, the cause is almost always in the
sFlow pipeline that feeds them, not in IXP Manager's web application. This document
follows that pipeline in the IXP Manager source, lists every place it loses or distorts
traffic, and gives a tool for each one. Tools are in [`tools/p2p/`](../tools/p2p).

Source references are to IXP Manager **v7.4.0**. The collector at DE-CIX India runs the
scripts from an IXP Manager **v5.7.0** checkout; the parts that matter are the same in
both (checked file by file, see [Versions](#versions)).

## How the pipeline works

```
switches ──sFlow/UDP 6343──▶ collector01
                              sflowtool -l  ──lines──▶  sflow-to-rrd-handler (perl, one process)
                                                          │  every 60s: GET <apibaseurl>/sflow-db-mapper/learned-macs
                                                          │  every 60s: write RRDs ──▶ rrdcached ──▶ /ixpmatrix/...
                                                          ▼
IXP Manager 7.4.0 (Grapher, sflow backend) ◀──HTTP── GRAPHER_BACKEND_SFLOW_ROOT (copies each .rrd, caches 5 min)
```

1. **sflowtool** prints one line per flow sample:
   `FLOW,agent,inPort,outPort,srcMAC,dstMAC,ethType,inVLAN,outVLAN,…,pktSize,ipSize,samplingRate`.
2. **sflow-to-rrd-handler** (`tools/runtime/sflow/sflow-to-rrd-handler`) looks up the
   source and destination MAC, *for the sample's VLAN tag*, in IXP Manager's MAC table.
   It keeps the sample only if **both** MACs are known and map to different VLAN
   interfaces. It then adds `pktSize × samplingRate` bytes to the matrix cell
   `[source VLI][destination VLI]`.
3. Every 60 s it writes the matrix out to RRD files:
   - one file per *ordered pair* of VLAN interfaces, per protocol (IPv4/IPv6) and type
     (bytes/packets);
   - one *individual* file per interface;
   - one *aggregate* file per VLAN.

   It divides by the measured interval to get a rate. It then re-fetches the MAC table
   and starts again from an empty matrix.
4. **IXP Manager** builds a P2P graph from `p2p.ipv4.bytes.src-A.dst-B.rrd`. It fetches
   the file over HTTP from the collector, keeps a local copy for 5 minutes, and reads it
   with `rrd_fetch` (`app/Utils/Grapher/Rrd.php`):
   - `traffic_out` is what A sent to B, and `traffic_in` is what A received from B.
   - The member's "all peers" view (multi-P2P) sums one file per peer
     (`app/Utils/Grapher/MultiRrd.php`).

## Where it goes wrong

Ordered by how likely each is to be the main cause at DE-CIX India's size, ~750
members.

### 1. The handler stops reading while it writes, and the cost grows with members²

The handler is a single loop. While it flushes, it reads no samples. During that time
sflowtool's output pipe fills and the kernel drops sFlow datagrams at the UDP socket. On
top of that, the flush writes **every pair's file, whether the pair exchanged traffic or
not**:

- The stock handler pre-fills the whole N×N matrix with zeros (`matrix_init`).
- `process_rrd` then visits every cell and creates any missing file.

So one flush is `4 × N × (N−1)` RRD updates, plus a `stat()` of every file.

| VLAN interfaces with a known MAC | pair files | updates per flush | disk at 182 KB per file |
|---|---|---|---|
| 50 | 9,800 | ~9,800 | 1.8 GB |
| 100 | 39,600 | ~40,000 | 7.2 GB |
| 750 | 2,247,000 | ~2.25 million | ~410 GB |

The last row explains why `/ixpmatrix` needed 541 GB. When a flush takes longer than a
small part of the 60 s cycle, two things happen:

- The samples that arrive during the flush are lost.
- The rate that is written divides what *was* read by the *whole* interval.

So every P2P value reads low. The loss is the same proportion for every pair and changes
with collector load: busier at peak time, and worse with each member added. That makes
it look like "the graphs are just inaccurate".

Measured on a test bench: the real 7.4.0 and 5.7.0 handlers, rrdcached, a simulated
sflowtool that drops what is not read, as a full socket buffer does, on a fast SSD, at
3,000 samples per second:

| members | stock handler: recorded / true | samples lost | improved handler: recorded / true | samples lost |
|---|---|---|---|---|
| 50 | 0.977 | 2.4% | 1.000 | 0% |
| 100 | 0.868 | 13.2% | 1.000 | 0% |

At 750 members, the work per flush is 57× the 100-member case. Unless the collector's
disks are far faster than the bench's, it is losing most of its samples.

**Check:** `collector-check.sh` watches rrdcached's update counter once a second. Each
flush shows up as a burst of busy seconds. It reports how long flushes take, how much of
the time the handler is not reading, and the UDP socket's drop counter.

**Fix:** `tools/p2p/sflow-to-rrd-handler`, a drop-in replacement (see
[Deploying](#deploying-the-improved-handler)):

- It flushes in a forked child, so reading never stops.
- It writes pairs that carried traffic every flush, and zeros to idle pairs every 5
  minutes.
- It creates no file for a pair that never exchanged traffic.

Same files, same format, same configuration.

### 2. MACs IXP Manager does not know: traffic that is silently dropped

A sample whose source or destination MAC is not in the table for that VLAN is dropped.
It is logged only with `--debug`. The member's P2P graphs then miss that traffic, or a
peer is missing altogether. Common reasons:

- **Learned MACs are stale or incomplete.** With the default `macdbtype` (learned), the
  table is IXP Manager's `macaddress` table. On IXP Manager's host,
  `tools/runtime/l2database/update-l2database.pl` rebuilds it from the switches' bridge
  tables over SNMP: `DELETE FROM macaddress`, then insert what it finds.
  - If a switch does not answer, every member on that switch loses its MACs until the
    next good run.
  - A member who replaced their router is unknown until the script runs again.
  - Check that this cron job survived the 7.4.0 upgrade.
- **Configured MACs are missing.** With `macdbtype = configured`, the table is what was
  entered per VLAN interface (`l2address`). A member whose router MAC changed, or who
  was never given one, is invisible.
- **Wrong VLAN tag.** The lookup is by the sample's VLAN tag:
  - A VLAN whose `number` in IXP Manager does not match the tag on the wire drops
    everything on it.
  - A switch that exports no VLAN for untagged frames (no "extended switch" record)
    reports VLAN 0, and everything from it is dropped.
- **Case or format.** sflowtool prints lowercase hex without separators. The stock
  handler matches exactly, so an entry stored as `AA:BB:…` never matches.
- **Duplicate MACs.** The same MAC on two virtual interfaces (a moved port, a reseller
  set-up) maps to whichever has the higher VLAN-interface id. The traffic is credited to
  the wrong member.

**Check:** `capture-and-audit.sh` captures live sFlow next to the running handler. It
replays the handler's own decision on every sample, against the same MAC table the
handler uses. It reports:

- how much traffic is dropped, for each reason;
- the unknown MACs, largest first, with the switch and port they came from;
- why each one missed: not in IXP Manager at all, known on another VLAN tag, or stored
  in a different format.

`collector-check.sh` flags an empty table, upper-case entries and an unreachable or
expired API key.

**Fix:** correct the MACs in IXP Manager, either the learned table's SNMP source or the
configured addresses. Find duplicates with:

```sql
-- learned
SELECT mac, COUNT(DISTINCT virtualinterfaceid) AS n, GROUP_CONCAT(DISTINCT virtualinterfaceid) AS vis
FROM macaddress GROUP BY mac HAVING n > 1;
-- configured (same MAC on two interfaces of one VLAN)
SELECT l.mac, vli.vlanid, GROUP_CONCAT(l.vlan_interface_id) AS vlis
FROM l2address l JOIN vlaninterface vli ON vli.id = l.vlan_interface_id
GROUP BY l.mac, vli.vlanid HAVING COUNT(*) > 1;
```

The improved handler also normalises MAC case and separators.

### 3. Packets sampled twice: graphs that read high

The handler counts every accepted sample. It relies on "the sflow accounting perimeter
on the switches" (its own comment) to see each packet exactly once. That only holds if
sFlow is enabled on **member-facing ports, ingress only**. If sFlow also runs on
inter-switch or core links, or samples egress, traffic that crosses the fabric is
counted at each point.

**Check:**

- The portal's *P2P accuracy* card shows sFlow recording **more** than the ports
  carried.
- `capture-and-audit.sh` lists input ports that carry many different members' traffic
  (core links). It also gives the share of counted traffic that was sampled away from
  the sender's own port.

**Fix:** switch configuration. Enable sFlow ingress-only on member ports, and disable it
on core, trunk and fan-out links.

### 4. Socket buffer too small for bursts

sflowtool asks the kernel for a 2,000,000-byte receive buffer. Linux caps it at
`net.core.rmem_max`, which is about 212 KB by default. Each flush stall, and each
MAC-table fetch, then overflows it sooner.

**Check:** `collector-check.sh`, under *Socket buffer* and *Loss on the collector*.

**Fix:** set `sysctl -w net.core.rmem_max=8388608` and persist it in
`/etc/sysctl.d/`. Then restart the handler so sflowtool asks again.

### 5. Recent data reads as zero: the rrdcached delay and the HTTP copy

rrdcached holds updates in memory for `-w` seconds (plus up to `-z` of random spread)
before writing them to the file. IXP Manager does not ask rrdcached. It copies the
on-disk file over HTTP and keeps that copy for 5 minutes. With `-w 1800`, the newest
30-60 minutes are not in the copy yet. `Rrd.php` turns unknown values into **0**, so:

- the right-hand end of every graph drops to zero;
- the "current" figure reads 0;
- the period average is pulled down.

**Check:** `collector-check.sh` (*Freshness*: how far the on-disk file trails
rrdcached), and `rrd-check.py lag`.

**Fix:**
- Use a shorter write delay, for example `-w 300 -z 60`.
- With the stock handler at 2 million files, that means rewriting the whole tree every 5
  minutes. With the improved handler there are only as many files as pairs that
  actually talk, so this is affordable.

### 6. Outages show as no traffic, not as gaps

The same NaN-to-0 conversion applies to any time the handler was down:
- the disk full;
- the API key refused;
- the handler crashed.

A member sees a valley, not a gap, and the averages and totals for the period are
understated by it.

**Check:** the portal's *P2P accuracy* card counts points where sFlow recorded nothing
while the ports carried traffic. `collector-check.sh` looks for `FATAL`, `Oops, input
pipe died`, `mactable reload failed` and `No space left` in the journal.

### 7. API key expiry: a scheduled outage

The 7.4.0 upgrade migration `2026_06_25_133900_set_api_keys_expires_not_nullable` gave
every key without an expiry date an expiry **12 months after the upgrade**. The
collector's key in `ixpmanager.conf` (`<ixp> apikey`) is one of those. When it expires:

- the MAC-table fetch returns 401;
- the handler keeps the old table for 24 hours, then exits with `FATAL: could not reload
  mactable`;
- P2P graphs stop.

The key also stops working if its user is disabled or its customer is inactive
(`ApiAuthenticate.php`).

**Check:** `collector-check.sh` reports the HTTP status of the fetch.

**Fix:** note the expiry date in IXP Manager (API keys page) and renew it in good time.

### 8. Sampling noise on small pairs

A 5-minute RRD point built from *n* samples is accurate to about ±196/√n %, at 95%
confidence. At 1-in-16,384 sampling, a pair exchanging a few Mb/s gets a handful of
samples per 5 minutes. Its graph is correct on average but jumps from point to point.

**Check:** `capture-and-audit.sh`, under *Statistical precision*. It shows how many
pairs, and how much traffic, fall into each error band.

**Fix:** sample more densely on ports where that matters, keeping within the switches'
sFlow limits. Or use week and month graphs for small pairs. The handler multiplies by
each sample's own rate, so mixed rates are fine.

### 9. Things IXP Manager itself gets wrong

These are not fixable on the collector; they are worth reporting upstream to INEX.

- **The PNG legend's "Avg" is an average of the MAX series.**
  - `Rrd.php` `png()` defines `VDEF:avg_in=cdefb,AVERAGE`, where `cdefb` is the MAX data
    source; `avg_out` does the same.
  - For day graphs it is harmless, because AVERAGE and MAX hold the same 5-minute
    values.
  - For week, month and year graphs, the "Avg" printed under the PNG is inflated.
  - The JSON/log data and IXP Manager's `Statistics` are not affected.
- **Multi-P2P (a member's traffic to all peers) silently skips files it cannot fetch.**
  - `MultiRrd::getLocalCopy()` returns `false` on any HTTP failure, and the file is left
    out of the sum.
  - One graph fetches one file per peer and protocol over HTTP, hundreds of 182 KB
    files. A slow or overloaded collector therefore yields a total that is too low, with
    no error shown.
- **`--infraid` never matched anything.**
  - `@infras = qw ( $infraid );` makes the literal string `$infraid`, not its value, so
    the handler drops every sample.
  - `collector-check.sh` flags it if it is set; the improved handler fixes it.

### How to read a P2P graph

For member A's graph with peer B:
- **Out** is traffic A sent to B; **In** is traffic A received from B.
- Both are measured where the traffic **enters** the exchange: B→A traffic is sampled on
  B's port.
- Non-IP traffic (ARP, LLDP) and broadcast/multicast are not counted, by design.

So the sum of a member's P2P graphs is slightly below the port graph even when
everything works. The portal's coverage card shows how much below.

## The tools

Run them in this order:

1. **Portal: IXP → Traffic → "P2P accuracy - sFlow against port counters".**
   - For each infrastructure, it compares the sum of the peering VLANs' sFlow
     aggregates (everything behind the P2P graphs) with the member ports' MRTG counters,
     point by point.
   - Expect 90-100%. Below that, samples are lost: causes 1, 2 and 4. Above, they are
     counted twice: cause 3.
   - Look at how the ratio moves through the day. A dip at peak hours points at cause 1.
   - It is also available as `GET /api/v1/ixp/sflow-coverage?period=day|week|month`.
2. **`collector-check.sh`** on the collector, as root:
   - It reads `ixpmanager.conf` like the handler does.
   - Then, over about two minutes, it measures UDP drops, handler CPU, flush duration
     and the on-disk lag.
   - It also checks the MAC-table API, disk, `rmem_max`, the rrdcached write delay and
     the journal.
   - Read only. Use `-w 600` if one flush may take minutes. Use `-x <url>` to also check
     the HTTP export IXP Manager reads.
3. **`capture-and-audit.sh`** on the collector, as root:
   - It captures sFlow for 2 minutes with tcpdump, which does not disturb the handler,
     and decodes it with sflowtool.
   - It fetches the same MAC table and runs `sflow-audit.py`.
   - Reported per drop reason: traffic share; unknown MACs, and why each missed.
   - Reported per switch: agents and their sampling rates; core links being sampled.
   - From the sequence numbers: datagram and sample loss between the switches and the
     collector, and drops the switches themselves report.
   - Delete the capture afterwards; it holds packet headers.
4. **`rrd-check.py`** on the collector:
   - `pair A B`: the A→B and B→A files must mirror each other. A mismatch means one
     flush wrote them far apart.
   - `sum A`: A's P2P files must add up to A's individual file. A shortfall means pair
     files are missing (disk full, failed creates).
   - `lag`: how far the on-disk files trail rrdcached.
   - `idle --days 90`: P2P files with no traffic at all, which are safe to delete
     **once the improved handler runs**. The stock handler recreates every pair's file
     on its next flush, so pruning under it frees nothing. Its every-minute zero writes
     also keep every file's mtime fresh, so a `find -mtime` prune finds nothing to
     delete.
   - Files with no data at all, as opposed to known zeros, are never listed.

Requirements:
- **Python scripts:** Python 3.8+ with only the standard library.
- **Shell scripts:** bash, curl, rrdtool, and socat or netcat-openbsd (for rrdcached's
  STATS).
- **Capture:** tcpdump and sflowtool, which the collector already has.

## Deploying the improved handler

`tools/p2p/sflow-to-rrd-handler` takes the same configuration file, command-line
options, input and output as the original. On collector01 (IXP Manager 5.7.0 tree in
`/srv/ixpmanager`):

1. Copy it next to the original. It finds `IXPManager::Config` through
   `../../perl-lib` the same way:
   ```sh
   install -m 755 sflow-to-rrd-handler /srv/ixpmanager/tools/runtime/sflow/sflow-to-rrd-handler.improved
   perl -c /srv/ixpmanager/tools/runtime/sflow/sflow-to-rrd-handler.improved
   ```
2. Point the service at it (`systemctl edit sflow-to-rrd-handler`, or the unit's
   `ExecStart`), with the same arguments as before. Then restart it.
3. Watch it for a few minutes with `journalctl -fu sflow-to-rrd-handler`. Each flush
   logs one line like this:
   ```
   flush: interval=60.0s duration=8.4s samples=412345 accepted=96.1% dropped: src_unknown=1.2% dst_unknown=0.9% dst_group=1.8% rrd: written=48211 created=12 prezero=37 errors=0 idle-every=5
   ```
   - `duration` can now exceed the interval without losing samples. If it does, the
     next interval is extended and a warning says so.
   - `accepted` and `dropped` are cause 2, measured continuously.
4. After a week, delete the files of pairs that never carried traffic. Read the list
   before deleting:
   ```sh
   rrd-check.py --base /ixpmatrix idle --days 90 -j 8 > /root/idle.txt
   xargs -a /root/idle.txt rm --
   ```
5. Lower rrdcached's write delay (cause 5) once the file count is down.

**Rollback:** point the service back at the original script and restart. The files are
compatible both ways. Pairs pruned in step 4 show "no data" in IXP Manager until they
exchange traffic again, as they would with any new member.

Differences in behaviour, all deliberate:

- **No file for a pair that never carried traffic.**
  - IXP Manager then shows that pair's graph as unavailable rather than a flat zero.
  - `--create-idle` restores the stock behaviour, at the stock cost.
- **Idle pairs get a zero every ~5 minutes, not every minute.** That is inside the
  RRDs' 600 s heartbeat, so they read 0, never unknown.
- **When an idle pair turns active, it first gets a zero at the previous flush time.**
  That keeps the new rate from being spread back over the idle minutes. A test
  (`tools/p2p/tests/test_handler.py`) checks that this holds, and fails without it.

## Versions

The collector runs scripts from IXP Manager 5.7.0; the web application there is not
used (no `vendor/`). Compared with 7.4.0:

- `tools/runtime/sflow/sflow-to-rrd-handler`: **same logic**. 5.7.0 splits all 20 fields
  of each sample, where 7.4.0 takes only the 8 it uses; the flush, the MAC lookup and
  the `--infraid` bug are identical.
- `tools/perl-lib/IXPManager`: identical.
- The API the handler calls, `/api/v4/sflow-db-mapper/learned-macs` (or
  `configured-macs`), is served by the 7.4.0 installation. It returns the same
  `{infrastructure: {tag: {mac: vli}}}` shape and still accepts the
  `X-IXP-Manager-API-Key` header with a legacy key (but see cause 7).

Upgrading the collector's checkout to 7.4.0 would not change any of the above.

## Tests

`tools/p2p/tests` runs under the backend's pytest:

```sh
cd backend && .venv/bin/pytest ../tools/p2p/tests
```

- The audit and RRD-checker tests run in under a second.
- The handler test needs perl's RRDs, JSON and REST::Client and the `rrdtool` binary. It
  runs the real handler for about 100 seconds against a scripted traffic pattern. It
  checks four things:
  - idle stretches read exactly zero;
  - nothing is smeared across reactivation;
  - quiet pairs get no file;
  - upper-case, colon-separated MACs still match.
