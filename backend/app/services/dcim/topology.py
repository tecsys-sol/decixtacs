"""Links between inventory devices discovered from their configurations.

* **subnet** - two devices hold the two addresses of a point-to-point subnet (/29../31, /112../127):
  a routed link, the strongest evidence.
* **description** - an interface (or the members of a LAG) is described with another device's
  hostname ("to mx204-ams1-core et-0/0/0"); the far side is paired when it names us back.

LAG members collapse onto their aggregate, so a 2x100G bundle is one 200G link. Parsed
interfaces are cached per device and commit, so the map stays cheap to redraw.
"""

from __future__ import annotations

import ipaddress
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Device
from app.services.backup.engine import device_relpath, store_for
from app.services.dcim import ports

_cache: dict[uuid.UUID, tuple[str, dict[str, ports.Interface]]] = {}
_lock = threading.Lock()

_SPEED_PREFIX = (
    ("et-", 100_000),
    ("xe-", 10_000),
    ("ge-", 1_000),
    ("mge-", 10_000),
    ("hundredgig", 100_000),
    ("fortygig", 40_000),
    ("twentyfivegig", 25_000),
    ("tengig", 10_000),
    ("gigabit", 1_000),
)


def speed_mbps(name: str) -> int | None:
    n = name.lower()
    for prefix, mbps in _SPEED_PREFIX:
        if n.startswith(prefix):
            return mbps
    return None


def latest_commits(db: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (device_id) device_id, commit_sha FROM config_backups "
            "WHERE tenant_id = :t AND commit_sha IS NOT NULL ORDER BY device_id, collected_at DESC"
        ),
        {"t": tenant_id},
    ).all()
    return {r[0]: r[1] for r in rows}


def parsed_interfaces(db: Session, tenant_id: uuid.UUID, devices: dict[uuid.UUID, Device]) -> dict[uuid.UUID, dict]:
    """device id -> {interface name: Interface} from the device's latest stored config."""
    store = store_for(db, tenant_id)
    out: dict[uuid.UUID, dict] = {}
    for did, sha in latest_commits(db, tenant_id).items():
        dev = devices.get(did)
        if dev is None:
            continue
        with _lock:
            hit = _cache.get(did)
        if hit and hit[0] == sha:
            out[did] = hit[1]
            continue
        content = store.read(device_relpath(dev), sha) or ""
        ifs = ports.parse(content, dev.platform.slug if dev.platform else None)
        with _lock:
            _cache[did] = (sha, ifs)
        out[did] = ifs
    return out


def is_p2p(net) -> bool:
    return (net.version == 4 and net.prefixlen >= 29) or (net.version == 6 and net.prefixlen >= 112)


@dataclass
class Side:
    device_id: uuid.UUID
    interface: str | None
    speed_mbps: int | None = None
    members: int = 1
    disabled: bool = False


@dataclass
class DiscoveredLink:
    a: Side
    b: Side
    source: str  # subnet|description
    detail: str | None = None  # e.g. the subnet
    extra: dict = field(default_factory=dict)

    @property
    def pair(self) -> frozenset:
        return frozenset((self.a.device_id, self.b.device_id))

    @property
    def speed(self) -> int | None:
        s = [x.speed_mbps * x.members for x in (self.a, self.b) if x.speed_mbps]
        return min(s) if s else None

    @property
    def up(self) -> bool:
        return not (self.a.disabled or self.b.disabled)


def _side(did: uuid.UUID, ifs: dict[str, ports.Interface], name: str | None) -> Side:
    """Describe one end; a LAG counts its members (and their speed)."""
    if name is None or name not in ifs:
        return Side(did, name, speed_mbps(name or ""))
    i = ifs[name]
    if i.is_lag:
        members = [m for m in ifs.values() if m.lag == name]
        return Side(
            did,
            name,
            speed_mbps(members[0].name) if members else None,
            max(1, len(members)),
            i.disabled or i.inactive,
        )
    return Side(did, name, speed_mbps(name), 1, i.disabled or i.inactive)


def discover_links(db: Session, tenant_id: uuid.UUID, devices: dict[uuid.UUID, Device]) -> list[DiscoveredLink]:
    parsed = parsed_interfaces(db, tenant_id, devices)
    links: list[DiscoveredLink] = []
    linked: set[tuple[uuid.UUID, str]] = set()  # (device, interface) already explained by a stronger link

    # --- point-to-point subnets
    ends: dict = defaultdict(list)
    for did, ifs in parsed.items():
        for i in ifs.values():
            for u in i.units.values():
                for a in u.addresses:
                    try:
                        ipi = ipaddress.ip_interface(a)
                    except ValueError:
                        continue
                    if is_p2p(ipi.network):
                        ends[ipi.network].append((did, i.name))
    for net, members in ends.items():
        devs = {d for d, _ in members}
        if len(members) != 2 or len(devs) != 2:
            continue
        (da, ia), (db_, ib) = sorted(members, key=lambda m: str(m[0]))
        links.append(DiscoveredLink(_side(da, parsed[da], ia), _side(db_, parsed[db_], ib), "subnet", detail=str(net)))
        linked |= {(da, ia), (db_, ib)}

    # --- descriptions naming another device
    names: dict[str, uuid.UUID] = {}
    for d in devices.values():
        if len(d.hostname) >= 4:
            names[d.hostname.lower()] = d.id
            names.setdefault(d.hostname.lower().split(".")[0], d.id)
    if names:
        rx = re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w-])", re.I
        )
        # (from device, to device) -> interfaces on "from" that name "to" (LAG members folded into the LAG)
        mentions: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = defaultdict(set)
        for did, ifs in parsed.items():
            for i in ifs.values():
                if ports.is_virtual(i.name):
                    continue
                texts = [i.description or ""] + [u.description or "" for u in i.units.values()]
                for t in texts:
                    for m in rx.finditer(t):
                        other = names[m.group(1).lower()]
                        if other != did:
                            mentions[(did, other)].add(i.lag or i.name)
        done: set[frozenset] = set()
        for (a, b), a_ifs in mentions.items():
            key = frozenset((a, b))
            if key in done:
                continue
            done.add(key)
            b_ifs = sorted(mentions.get((b, a), set()))
            a_list = sorted(a_ifs)
            for n, ai in enumerate(a_list):
                if (a, ai) in linked:
                    continue
                # pair far-side interfaces only when both ends name each other one-to-one
                bi = b_ifs[n] if len(b_ifs) == len(a_list) else None
                if bi is not None and (b, bi) in linked:
                    continue
                links.append(DiscoveredLink(_side(a, parsed[a], ai), _side(b, parsed[b], bi), "description"))
                linked.add((a, ai))
                if bi:
                    linked.add((b, bi))
    return links
