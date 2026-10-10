"""Links between inventory devices discovered from what the devices report and their configurations.

* **lldp** - LLDP neighbours collected with each backup: what the ports actually see. The only
  source for layer-2 links (IXP fabric trunks) that carry no addresses.
* **subnet** - two devices hold the two addresses of a point-to-point subnet (/29../31, /112../127):
  a routed link. On a link LLDP already found it only adds the subnet as detail.
* **description** - an interface (or the members of a LAG) is described with another device's
  hostname ("to mx204-ams1-core et-0/0/0"); the far port is taken from the description when it
  names one, else paired when the far side names us back.

The configuration used is NOM's latest backup, else RANCID's newest revision (imported CVS
history or the uploaded configs), so devices NOM cannot back up yet still take part.

LAG members collapse onto their aggregate, so a 2x100G bundle is one 200G link. Parsed
interfaces are cached per device and commit, so the map stays cheap to redraw.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from sqlalchemy import select, text
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


@dataclass
class ConfigSource:
    key: str  # cache key: changes when the content does
    source: str  # nom|rancid_history|rancid_upload
    reader: Callable[[], str | None]
    _text: str | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self.reader() or ""
        return self._text


def device_configs(
    db: Session, tenant_id: uuid.UUID, devices: dict[uuid.UUID, Device]
) -> dict[uuid.UUID, ConfigSource]:
    """The newest configuration known for each device: NOM's latest backup, else the newest revision
    imported from RANCID's CVS history, else the config uploaded for the RANCID comparison - so
    devices NOM cannot back up yet still show their ports and links. Content is read on demand."""
    from app.models import RancidConfig
    from app.services import rancid as rs
    from app.services import rancid_history

    out: dict[uuid.UUID, ConfigSource] = {}
    store = store_for(db, tenant_id)
    for did, sha in latest_commits(db, tenant_id).items():
        dev = devices.get(did)
        if dev is not None:
            out[did] = ConfigSource(f"nom:{sha}", "nom", partial(store.read, device_relpath(dev), sha))
    missing = [d for d in devices.values() if d.id not in out]
    hist = rancid_history.history_store(db, tenant_id) if missing else None
    if hist is not None:
        for d in missing:
            path = device_relpath(d)
            sha = hist.last_commit(path)
            if sha:
                out[d.id] = ConfigSource(f"rancid:{sha}", "rancid_history", partial(hist.read, path, sha))
    missing = [d for d in devices.values() if d.id not in out]
    if missing:
        by_id = {d.id: d for d in missing}
        by_short = {rs.short(d.hostname): d for d in missing}
        for rc in db.scalars(select(RancidConfig).where(RancidConfig.tenant_id == tenant_id)):
            d = by_id.get(rc.device_id) if rc.device_id else by_short.get(rs.short(rc.name))
            if d is None or d.id in out:
                continue
            plat = d.platform.slug if d.platform else None
            digest = hashlib.sha256(rc.content.encode()).hexdigest()[:16]
            out[d.id] = ConfigSource(
                f"upload:{digest}", "rancid_upload", partial(rancid_history.to_nom_format, rc.content, plat, False)
            )
    return out


def device_config(db: Session, tenant_id: uuid.UUID, dev: Device) -> ConfigSource | None:
    return device_configs(db, tenant_id, {dev.id: dev}).get(dev.id)


def parsed_interfaces(db: Session, tenant_id: uuid.UUID, devices: dict[uuid.UUID, Device]) -> dict[uuid.UUID, dict]:
    """device id -> {interface name: Interface} from the device's newest known config."""
    out: dict[uuid.UUID, dict] = {}
    for did, cs in device_configs(db, tenant_id, devices).items():
        dev = devices[did]
        with _lock:
            hit = _cache.get(did)
        if hit and hit[0] == cs.key:
            out[did] = hit[1]
            continue
        ifs = ports.parse(cs.text, dev.platform.slug if dev.platform else None)
        with _lock:
            _cache[did] = (cs.key, ifs)
        out[did] = ifs
    return out


_SEP = r"[-_. ]?"
_ASN = re.compile(r"(?<![A-Za-z0-9])AS[\s_:-]?(\d{1,10})(?!\d)", re.I)


def asns_in(text: str) -> list[int]:
    """ASNs named in a description: "AS13335", "AS 13335", "AS-13335 Cloudflare", "as13335_cf"."""
    return [int(m.group(1)) for m in _ASN.finditer(text or "")]


class DeviceNames:
    """Finds inventory devices named in free text (interface descriptions). Matches the full
    hostname or its first label, case-insensitively, with or without the separators between its
    parts ("DEL-02-IXP01", "del02-ixp01", "TO_DEL-02-IXP01_et-0/0/1", "del-02-ixp01.del.int...")."""

    def __init__(self, devices):
        self.by_key: dict[str, object] = {}
        for d in devices:
            for name in {d.hostname.lower(), d.hostname.lower().split(".")[0]}:
                key = re.sub(r"[^a-z0-9]", "", name)
                if len(key) >= 4:
                    self.by_key.setdefault(key, d)
        self.rx = None
        if self.by_key:
            alts = []
            for d in devices:
                for name in {d.hostname.lower(), d.hostname.lower().split(".")[0]}:
                    parts = [p for p in re.split(r"[^a-z0-9]+", name) if p]
                    if len("".join(parts)) >= 4:
                        alts.append(_SEP.join(re.escape(p) for p in parts))
            alts = sorted(set(alts), key=len, reverse=True)
            self.rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(alts) + r")(?![A-Za-z0-9])", re.I)

    def find(self, text: str) -> list:
        out = []
        for d, _tail in self.find_with_tail(text):
            if d not in out:
                out.append(d)
        return out

    def find_with_tail(self, text: str) -> list[tuple[object, str]]:
        """[(device, text after the name)] - the tail usually names the far-end port."""
        if not self.rx or not text:
            return []
        out = []
        for m in self.rx.finditer(text):
            d = self.by_key.get(re.sub(r"[^a-z0-9]", "", m.group(1).lower()))
            if d is not None:
                out.append((d, text[m.end() :]))
        return out


_IFTOKEN = re.compile(r"[A-Za-z][A-Za-z-]*\s?\d+(?:[/:.]\d+)*")


def canonical_ifname(token: str, ifs: dict[str, ports.Interface]) -> str | None:
    """The interface of ``ifs`` a short or abbreviated name refers to ("Gi0/0/1", "et-0/0/1", "Eth1/1")."""
    t = token.strip().replace(" ", "")
    if not t:
        return None
    if t in ifs:
        return t
    low = {n.lower(): n for n in ifs}
    if t.lower() in low:
        return low[t.lower()]
    m = re.match(r"^([A-Za-z-]*?)-?(\d+(?:[/:]\d+)*)$", t)
    if not m:
        return None
    prefix, nums = m.group(1).lower(), m.group(2)
    if not prefix and not re.search(r"[/:]", nums):
        return None  # a bare number (SNMP ifIndex, "1") names no port reliably
    cands = [
        n
        for n in ifs
        if re.match(r"^([A-Za-z-]*?)-?(\d+(?:[/:]\d+)*)$", n)
        and re.match(r"^([A-Za-z-]*?)-?(\d+(?:[/:]\d+)*)$", n).group(2) == nums
        and (not prefix or n.lower().startswith(prefix))
    ]
    return cands[0] if len(cands) == 1 else None


def port_hint(tail: str, ifs: dict[str, ports.Interface]) -> str | None:
    """First interface of the far device named in a description tail, folded into its LAG."""
    for m in _IFTOKEN.finditer(tail[:60]):
        name = canonical_ifname(m.group(0), ifs)
        if name:
            i = ifs[name]
            return i.lag or name
    return None


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


@dataclass
class SeenNeighbor:
    """An LLDP neighbour with both ends resolved as far as the inventory allows."""

    device_id: uuid.UUID
    local: str  # local interface (canonical config name, LAG member folded into its LAG)
    local_port: str  # the physical port as LLDP reported it (canonicalised)
    remote_device: object | None  # inventory Device or None
    remote_port: str | None  # far port, canonical + LAG-folded when the far device is known
    raw: object  # the DeviceNeighbor row


def resolve_neighbors(
    db: Session,
    tenant_id: uuid.UUID,
    devices: dict[uuid.UUID, Device],
    parsed: dict[uuid.UUID, dict],
    names: DeviceNames | None = None,
) -> dict[uuid.UUID, list[SeenNeighbor]]:
    from app.models import DeviceNeighbor

    if not devices:
        return {}
    names = names or DeviceNames(list(devices.values()))
    by_ip = {d.management_ip: d for d in devices.values() if d.management_ip}
    out: dict[uuid.UUID, list[SeenNeighbor]] = defaultdict(list)
    rows = db.scalars(
        select(DeviceNeighbor).where(DeviceNeighbor.tenant_id == tenant_id, DeviceNeighbor.device_id.in_(list(devices)))
    )
    for n in rows:
        mine = parsed.get(n.device_id, {})
        port = canonical_ifname(n.local_interface, mine) or n.local_interface
        local = mine[port].lag or port if port in mine else port
        remote = None
        for cand in filter(None, [n.remote_system, (n.remote_system or "").split(".")[0]]):
            remote = names.by_key.get(re.sub(r"[^a-z0-9]", "", cand.lower()))
            if remote is not None:
                break
        if remote is None and n.remote_address:
            remote = by_ip.get(n.remote_address)
        rport = None
        if remote is not None:
            theirs = parsed.get(remote.id, {})
            for cand in filter(None, [n.remote_port, n.remote_port_description]):
                name = canonical_ifname(cand, theirs)
                if name:
                    rport = theirs[name].lag or name
                    break
            if rport is None and not theirs:
                # far device without a parsed config: keep what LLDP said, unless it is an ifIndex
                rport = next((c for c in (n.remote_port, n.remote_port_description) if c and not c.isdigit()), None)
        if remote is not None and remote.id == n.device_id:
            continue
        out[n.device_id].append(SeenNeighbor(n.device_id, local, port, remote, rport, n))
    return out


def _lldp_links(seen: dict[uuid.UUID, list[SeenNeighbor]], parsed: dict[uuid.UUID, dict]) -> list[DiscoveredLink]:
    """One link per (port, far port); both ends' reports merged, LAG members folded."""
    views: dict[tuple, list[tuple[str, str | None]]] = defaultdict(list)  # (a, b) -> [(a port, b port?)]
    for did, items in seen.items():
        for sn in items:
            if sn.remote_device is not None:
                views[(did, sn.remote_device.id)].append((sn.local, sn.remote_port))
    links: list[DiscoveredLink] = []
    done: set[frozenset] = set()
    for a, b in list(views):
        key = frozenset((a, b))
        if key in done:
            continue
        done.add(key)
        pairs: set[tuple[str, str]] = set()
        half_a: list[str] = []
        half_b: list[str] = []
        for ai, bi in views.get((a, b), []):
            if bi:
                pairs.add((ai, bi))
            else:
                half_a.append(ai)
        for bi, ai in views.get((b, a), []):
            if ai:
                pairs.add((ai, bi))
            else:
                half_b.append(bi)
        known_a = {p[0] for p in pairs}
        known_b = {p[1] for p in pairs}
        half_a = sorted(set(x for x in half_a if x not in known_a))
        half_b = sorted(set(x for x in half_b if x not in known_b))
        if len(half_a) == len(half_b):
            pairs |= set(zip(half_a, half_b, strict=True))
            half_a, half_b = [], []
        pa, pb = parsed.get(a, {}), parsed.get(b, {})
        for ai, bi in sorted(pairs):
            links.append(DiscoveredLink(_side(a, pa, ai), _side(b, pb, bi), "lldp"))
        for ai in half_a:
            links.append(DiscoveredLink(_side(a, pa, ai), _side(b, pb, None), "lldp"))
        for bi in half_b:
            links.append(DiscoveredLink(_side(a, pa, None), _side(b, pb, bi), "lldp"))
    return links


def discover_links(
    db: Session, tenant_id: uuid.UUID, devices: dict[uuid.UUID, Device], *, lldp: bool = True
) -> list[DiscoveredLink]:
    parsed = parsed_interfaces(db, tenant_id, devices)
    names = DeviceNames(list(devices.values()))
    links: list[DiscoveredLink] = []
    linked: set[tuple[uuid.UUID, str]] = set()  # (device, interface) already explained by a stronger link
    by_end: dict[tuple[uuid.UUID, str], DiscoveredLink] = {}

    # --- LLDP: what the devices actually see on their ports
    seen = resolve_neighbors(db, tenant_id, devices, parsed, names) if lldp else {}
    for lk in _lldp_links(seen, parsed):
        links.append(lk)
        for side in (lk.a, lk.b):
            if side.interface:
                linked.add((side.device_id, side.interface))
                by_end[(side.device_id, side.interface)] = lk

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
        # the routed subnet on a link LLDP already found: annotate it instead of drawing it twice
        ia_l = parsed[da][ia].lag or ia if ia in parsed[da] else ia
        ib_l = parsed[db_][ib].lag or ib if ib in parsed[db_] else ib
        seen_lk = by_end.get((da, ia)) or by_end.get((da, ia_l))
        if seen_lk is not None and seen_lk is (by_end.get((db_, ib)) or by_end.get((db_, ib_l))):
            seen_lk.detail = seen_lk.detail or str(net)
            continue
        links.append(DiscoveredLink(_side(da, parsed[da], ia), _side(db_, parsed[db_], ib), "subnet", detail=str(net)))
        linked |= {(da, ia), (db_, ib)}

    # --- descriptions naming another device
    if names.rx:
        # (from device, to device) -> {interface on "from" (LAG members folded): far port it names, if any}
        mentions: dict[tuple[uuid.UUID, uuid.UUID], dict[str, str | None]] = defaultdict(dict)
        for did, ifs in parsed.items():
            for i in ifs.values():
                if i.is_virtual:
                    continue
                texts = [i.description or ""] + [u.description or "" for u in i.units.values()]
                for t in texts:
                    for other_dev, tail in names.find_with_tail(t):
                        other = other_dev.id
                        if other == did:
                            continue
                        mine = i.lag or i.name
                        hint = port_hint(tail, parsed[other]) if other in parsed else None
                        if mentions[(did, other)].get(mine) is None:
                            mentions[(did, other)][mine] = hint
        done: set[frozenset] = set()
        for (a, b), a_map in mentions.items():
            key = frozenset((a, b))
            if key in done:
                continue
            done.add(key)
            b_map = mentions.get((b, a), {})
            pairs: list[tuple[str | None, str | None]] = []
            used_a: set[str] = set()
            used_b: set[str] = set()
            # 1. a description names the far port, or the far port names us back
            for ai, hint in sorted(a_map.items()):
                bi = hint or next((x for x, h in b_map.items() if h == ai), None)
                if bi is not None and bi not in used_b:
                    pairs.append((ai, bi))
                    used_a.add(ai)
                    used_b.add(bi)
            for bi, hint in sorted(b_map.items()):
                if bi in used_b or not hint or hint in used_a:
                    continue
                pairs.append((hint, bi))
                used_a.add(hint)
                used_b.add(bi)
            # 2. the rest: pair one-to-one when both ends list the same number of ports
            rest_a = [x for x in sorted(a_map) if x not in used_a]
            rest_b = [x for x in sorted(b_map) if x not in used_b]
            for n, ai in enumerate(rest_a):
                pairs.append((ai, rest_b[n] if len(rest_b) == len(rest_a) else None))
            if not rest_a:
                pairs += [(None, bi) for bi in rest_b]
            for ai, bi in pairs:
                if (ai and (a, ai) in linked) or (bi and (b, bi) in linked):
                    continue
                pa = parsed.get(a, {})
                pb = parsed.get(b, {})
                links.append(DiscoveredLink(_side(a, pa, ai), _side(b, pb, bi), "description"))
                if ai:
                    linked.add((a, ai))
                if bi:
                    linked.add((b, bi))
    return links


# --- customers: routers outside the inventory --------------------------------------------------------


@dataclass
class Customer:
    key: str  # "as13335" or "lldp:<system name>"
    label: str
    asn: int | None = None
    name: str | None = None  # IXP member / LLDP system name
    devices: list[uuid.UUID] = field(default_factory=list)  # where it is attached


@dataclass
class CustomerLink:
    device_id: uuid.UUID
    interface: str | None
    customer: str  # Customer.key
    source: str  # description|lldp|ixpmanager
    speed_mbps: int | None = None
    disabled: bool = False
    remote_port: str | None = None
    detail: str | None = None


def discover_customers(
    db: Session,
    tenant_id: uuid.UUID,
    devices: dict[uuid.UUID, Device],
    device_links: list[DiscoveredLink],
    *,
    lldp: bool = True,
) -> tuple[dict[str, Customer], list[CustomerLink]]:
    """Customer routers attached to inventory devices: ports whose description names an ASN
    ("CUST-1010 AS64510"), LLDP neighbours that are not in the inventory, and IXP Manager member
    connections on switches that are. One node per customer (by ASN when it is known), so a member
    found by several sources is drawn once; ports already linked to an inventory device are skipped."""
    from app.models import IxpMember

    parsed = parsed_interfaces(db, tenant_id, devices)
    names = DeviceNames(list(devices.values()))
    members = {m.asn: m for m in db.scalars(select(IxpMember).where(IxpMember.tenant_id == tenant_id))}
    linked = {(s.device_id, s.interface) for lk in device_links for s in (lk.a, lk.b) if s.interface}
    customers: dict[str, Customer] = {}
    links: dict[tuple, CustomerLink] = {}

    def customer(asn: int | None, system: str | None) -> Customer:
        if asn is not None:
            key = f"as{asn}"
            m = members.get(asn)
            label = f"AS{asn} {m.name}" if m else f"AS{asn}"
            c = customers.setdefault(key, Customer(key, label, asn, m.name if m else system))
        else:
            key = "lldp:" + re.sub(r"[^a-z0-9.-]", "", (system or "").lower())
            c = customers.setdefault(key, Customer(key, system or "LLDP neighbour", None, system))
        return c

    def attach(c: Customer, did: uuid.UUID, iface: str | None, source: str, **extra) -> None:
        if did not in c.devices:
            c.devices.append(did)
        k = (did, iface, c.key)
        if k in links:
            return
        if iface is None and any(x[0] == did and x[2] == c.key for x in links):
            return  # already attached on a known port
        side = _side(did, parsed.get(did, {}), iface)
        links[k] = CustomerLink(
            did, iface, c.key, source, side.speed_mbps and side.speed_mbps * side.members, side.disabled, **extra
        )

    # 1. port descriptions naming an ASN; 2. LLDP neighbours outside the inventory on the same ports
    lldp_seen = resolve_neighbors(db, tenant_id, devices, parsed, names) if lldp else {}
    unresolved: dict[tuple[uuid.UUID, str], list] = defaultdict(list)
    for did, items in lldp_seen.items():
        for sn in items:
            if sn.remote_device is None and (sn.raw.remote_system or sn.raw.remote_chassis):
                unresolved[(did, sn.local)].append(sn)
    for did, ifs in parsed.items():
        for i in ifs.values():
            if i.is_virtual or i.lag or (did, i.name) in linked:
                continue  # LAG members count through their LAG
            texts = [i.description or ""] + [u.description or "" for u in i.units.values()]
            asns = [a for t in texts for a in asns_in(t)]
            if names.find(" ".join(texts)):
                continue  # the port names an inventory device: not a customer port
            seen_here = unresolved.pop((did, i.name), [])
            if asns:
                for asn in dict.fromkeys(asns):
                    c = customer(asn, seen_here[0].raw.remote_system if seen_here else None)
                    attach(
                        c,
                        did,
                        i.name,
                        "lldp" if seen_here else "description",
                        remote_port=(seen_here[0].raw.remote_port_description or seen_here[0].raw.remote_port)
                        if seen_here
                        else None,
                        detail=i.description,
                    )
            for sn in seen_here if not asns else []:
                c = customer(None, sn.raw.remote_system or sn.raw.remote_chassis)
                attach(c, did, i.name, "lldp", remote_port=sn.raw.remote_port_description or sn.raw.remote_port)
    for (did, local), items in unresolved.items():  # LLDP on ports without a parsed config
        if (did, local) in linked:
            continue
        for sn in items:
            c = customer(None, sn.raw.remote_system or sn.raw.remote_chassis)
            attach(c, did, local, "lldp", remote_port=sn.raw.remote_port_description or sn.raw.remote_port)

    # 3. IXP Manager: every member connection names the switch it is on
    for asn, m in members.items():
        for conn in m.connections or []:
            for p in conn.get("ports") or []:
                sw = names.by_key.get(re.sub(r"[^a-z0-9]", "", str(p.get("switch") or "").lower()))
                if sw is None:
                    continue
                c = customer(asn, None)
                if not any(x.device_id == sw.id and x.customer == c.key for x in links.values()):
                    if sw.id not in c.devices:
                        c.devices.append(sw.id)
                    links[(sw.id, None, c.key, len(links))] = CustomerLink(
                        sw.id, None, c.key, "ixpmanager", p.get("speed_mbps")
                    )
    return customers, list(links.values())
