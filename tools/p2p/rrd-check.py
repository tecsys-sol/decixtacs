#!/usr/bin/env python3
"""Check the P2P RRD files on the sFlow collector against each other.

Every number in these files comes from one traffic matrix, so they must agree:

  pair A B     the A->B file's "in" is the B->A file's "out", sample for sample; also
               shows how far the on-disk copy (what IXP Manager fetches over HTTP)
               trails rrdcached
  sum A        the sum of all of A's P2P files equals A's individual file; a shortfall
               means P2P files are missing (disk full, failed creates)
  lag          how far files on disk trail rrdcached, on a random sample
  idle         P2P files with no traffic at all in the last N days: safe to delete
               once the improved handler runs (the stock 7.4.0 handler recreates every
               pair's file on its next flush)

Run on the collector. Needs the rrdtool binary. Python 3.8+, standard library only.

  rrd-check.py pair 123 456
  rrd-check.py sum 123 --days 7
  rrd-check.py idle --days 90 -j 8 > idle.txt   # then: xargs -a idle.txt rm --
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

SOCK = "unix:/var/run/rrdcached.sock"


def daemon_opts(args) -> list[str]:
    path = args.daemon.split(":", 1)[-1]
    return ["--daemon", args.daemon] if args.daemon and os.path.exists(path) else []


def fetch(
    path: str, start: int, end: int, daemon: list[str], cf: str = "AVERAGE"
) -> list[tuple[int, float | None, float | None]]:
    out = subprocess.run(
        ["rrdtool", "fetch", path, cf, "-s", str(start), "-e", str(end), *daemon], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"rrdtool fetch {path} failed")
    rows = []
    for ln in out.stdout.splitlines():
        head, _, vals = ln.partition(":")
        if not vals or not head.strip().isdigit():
            continue
        v = [None if "nan" in x.lower() else float(x) for x in vals.split()]
        rows.append((int(head), v[0], v[1] if len(v) > 1 else None))
    return rows


def last(path: str, daemon: list[str]) -> int | None:
    if daemon:
        out = subprocess.run(["rrdtool", "lastupdate", path, *daemon], capture_output=True, text=True)
        for ln in out.stdout.splitlines():
            head = ln.split(":")[0].strip()
            if head.isdigit():
                return int(head)
        return None
    out = subprocess.run(["rrdtool", "last", path], capture_output=True, text=True)
    return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else None


def p2p_path(base: str, proto: int, kind: str, src: int, dst: int) -> str:
    return f"{base}/ipv{proto}/{kind}/p2p/src-{src:05d}/p2p.ipv{proto}.{kind}.src-{src:05d}.dst-{dst:05d}.rrd"


def ind_path(base: str, proto: int, kind: str, vli: int) -> str:
    return f"{base}/ipv{proto}/{kind}/individual/individual.ipv{proto}.{kind}.src-{vli:05d}.rrd"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def human(bps: float | None) -> str:
    if bps is None:
        return "     n/a"
    v = bps * 8
    for unit in ("b/s", "kb/s", "Mb/s", "Gb/s"):
        if v < 1000:
            return f"{v:6.1f} {unit}"
        v /= 1000
    return f"{v:6.1f} Tb/s"


def cmd_pair(a) -> int:
    end = int(time.time())
    start = end - int(a.days * 86400)
    d = daemon_opts(a)
    bad = 0
    for proto in (4, 6):
        ab, ba = p2p_path(a.base, proto, "bytes", a.a, a.b), p2p_path(a.base, proto, "bytes", a.b, a.a)
        print(f"\n== IPv{proto}")
        if not (os.path.exists(ab) and os.path.exists(ba)):
            print(f"   missing: {', '.join(p for p in (ab, ba) if not os.path.exists(p))}")
            bad += 1
            continue
        r1, r2 = fetch(ab, start, end, d), fetch(ba, start, end, d)
        m1 = {t: (i, o) for t, i, o in r1}
        m2 = {t: (i, o) for t, i, o in r2}
        common = sorted(set(m1) & set(m2))
        unknown = sum(1 for t in common if m1[t][0] is None)
        print(
            f"   {a.a}->{a.b}: avg out {human(mean(m1[t][1] for t in common))}, "
            f"in {human(mean(m1[t][0] for t in common))}"
            f"   ({unknown}/{len(common)} points unknown)"
        )
        # A's "in" from B is B's "out" to A
        diffs = []
        for t in common:
            x, y = m1[t][0], m2[t][1]
            if x is not None and y is not None and max(x, y) > 0:
                diffs.append(abs(x - y) / max(x, y))
        if diffs:
            diffs.sort()
            p50, p95 = diffs[len(diffs) // 2], diffs[min(len(diffs) - 1, int(len(diffs) * 0.95))]
            ok = p95 < 0.02
            bad += 0 if ok else 1
            print(
                f"   symmetry: {a.a}<-{a.b} vs {a.b}->{a.a} differ by median {100 * p50:.2f}%, p95 {100 * p95:.2f}%"
                + ("" if ok else "  <- the two files were updated far apart: flushes are taking too long")
            )
        else:
            print("   symmetry: no traffic in the window to compare")
        if d:
            mem, disk = last(ab, d), last(ab, [])
            if mem and disk:
                print(f"   on disk {mem - disk}s behind rrdcached (IXP Manager copies the on-disk file over HTTP)")
    return 1 if bad else 0


def cmd_sum(a) -> int:
    end = int(time.time())
    start = end - int(a.days * 86400)
    d = daemon_opts(a)
    worst = 0.0
    for proto in (4, 6):
        ind = ind_path(a.base, proto, "bytes", a.a)
        sdir = os.path.dirname(p2p_path(a.base, proto, "bytes", a.a, 0))
        if not os.path.exists(ind):
            print(f"IPv{proto}: no individual file {ind}")
            continue
        files = sorted(os.path.join(sdir, f) for f in os.listdir(sdir)) if os.path.isdir(sdir) else []
        tin = tout = 0.0
        for f in files:
            for _, i, o in fetch(f, start, end, d):
                tin += i or 0
                tout += o or 0
        iin = iout = 0.0
        for _, i, o in fetch(ind, start, end, d):
            iin += i or 0
            iout += o or 0
        if not (iout or iin):
            print(f"IPv{proto}: {len(files)} P2P files; no traffic in the window")
            continue
        cov_out = tout / iout if iout else 1.0
        cov_in = tin / iin if iin else 1.0
        print(f"IPv{proto}: {len(files)} P2P files; P2P sum / individual: sent {cov_out:.3f}, received {cov_in:.3f}")
        worst = max(worst, abs(1 - cov_out), abs(1 - cov_in))
    if worst > 0.02:
        print("P2P files do not add up to the member total: some pair files are missing or were not updated")
        return 1
    return 0


def cmd_lag(a) -> int:
    d = daemon_opts(a)
    if not d:
        print(f"rrdcached socket {a.daemon} not found - nothing to compare")
        return 1
    files = []
    for root, _, fs in os.walk(os.path.join(a.base, "ipv4", "bytes")):
        files += [os.path.join(root, f) for f in fs if f.endswith(".rrd")]
        if len(files) > 50000:
            break
    sample = random.sample(files, min(a.sample, len(files)))
    lags = []
    for f in sample:
        mem, disk = last(f, d), last(f, [])
        if mem and disk:
            lags.append(mem - disk)
    if not lags:
        print("no files to compare")
        return 1
    lags.sort()
    print(f"{len(lags)} files: on disk behind rrdcached by median {lags[len(lags) // 2]}s, max {lags[-1]}s")
    print("IXP Manager reads the on-disk file over HTTP, so the newest part of each graph is that much behind;")
    print("it shows as zero, not as missing. Lower rrdcached -w, or flush before serving.")
    return 0


def cmd_idle(a) -> int:
    end = int(time.time())
    start = end - int(a.days * 86400)
    files = []
    for proto in (4, 6):
        for kind in ("bytes", "pkts"):
            root = os.path.join(a.base, f"ipv{proto}", kind, "p2p")
            for r, _, fs in os.walk(root):
                files += [os.path.join(r, f) for f in fs if f.endswith(".rrd")]
    print(
        f"scanning {len(files)} P2P files for traffic since {time.strftime('%Y-%m-%d', time.localtime(start))} ...",
        file=sys.stderr,
    )

    def idle(f):
        try:
            rows = fetch(f, start, end, [], cf="MAX")
        except RuntimeError:
            return None
        known = [(i, o) for _, i, o in rows if i is not None or o is not None]
        # all-unknown means "no data" (handler down, file new), not "no traffic": keep it
        return f if known and all(not (i or o) for i, o in known) else None

    n = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(idle, files, chunksize=64):
            if res:
                print(res)
                n += 1
    per = 182400  # bytes in one file as the handler creates it
    print(f"{n} of {len(files)} files carried no traffic; about {n * per / 1e9:.1f} GB", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="/data/ixpmatrix", help="sflow_rrddir (default /data/ixpmatrix)")
    ap.add_argument("--daemon", default=SOCK, help=f"rrdcached address (default {SOCK}); '' to read files only")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair")
    p.add_argument("a", type=int)
    p.add_argument("b", type=int)
    p.add_argument("--days", type=float, default=1)
    s = sub.add_parser("sum")
    s.add_argument("a", type=int)
    s.add_argument("--days", type=float, default=1)
    lag = sub.add_parser("lag")
    lag.add_argument("--sample", type=int, default=20)
    i = sub.add_parser("idle")
    i.add_argument("--days", type=float, default=90)
    i.add_argument("-j", "--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    return {"pair": cmd_pair, "sum": cmd_sum, "lag": cmd_lag, "idle": cmd_idle}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
