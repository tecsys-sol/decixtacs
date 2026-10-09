"""Interfaces as the device configuration defines them.

Parses the stored configuration (Junos ``display set``, IOS / IOS-XE / NX-OS / EOS) into physical
and logical interfaces with description, admin state, LAG membership, MTU/speed, units (VLAN, IPv4/
IPv6 addresses, switching VLANs) and the routing protocols enabled on them. The result is matched
to the front-panel ports of the device type (``devicetypes.py``) by ``port_key``.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass, field

# Junos logical/system interfaces that are never a front-panel port
_JUNOS_VIRTUAL = re.compile(
    r"^(lo\d*|irb|vlan|vme|dsc|gr-|ip-|lt-|mt-|pd-|pe-|pfe-|pfh-|tap|vtep|st0|ms-|si-|sp-|jsrv|bme|em\d)"
)
_IOS_VIRTUAL = re.compile(r"^(loopback|vlan|tunnel|nve|null|bdi|virtual|dialer|bvi|mgmt\d?$)", re.I)
_LAG = re.compile(r"^(ae\d+|reth\d+|port-channel\s*\d+|bundle-ether\d+|po\d+|bond\d+)$", re.I)


@dataclass
class Unit:
    name: str  # "0", "446" (Junos) or "" for IOS main interface / subinterface id
    description: str | None = None
    vlan: int | None = None
    addresses: list[str] = field(default_factory=list)  # CIDR
    switching: dict = field(default_factory=dict)  # {"mode": "trunk"|"access", "vlans": [...]}
    protocols: set[str] = field(default_factory=set)  # bgp/ospf/isis/ldp/mpls/lldp ...
    disabled: bool = False
    vrf: str | None = None


@dataclass
class Interface:
    name: str
    description: str | None = None
    disabled: bool = False
    inactive: bool = False  # Junos "deactivate"
    lag: str | None = None  # parent aggregate (ae0 / Port-Channel10)
    mtu: int | None = None
    speed: str | None = None
    units: dict[str, Unit] = field(default_factory=dict)
    protocols: set[str] = field(default_factory=set)
    kind: str | None = None  # "lag" / "virtual" when the config says so (FortiOS, RouterOS, VyOS)

    @property
    def is_lag(self) -> bool:
        return self.kind == "lag" or bool(_LAG.match(self.name))

    @property
    def is_virtual(self) -> bool:
        return self.kind == "virtual" or is_virtual(self.name)

    def unit(self, name: str) -> Unit:
        return self.units.setdefault(name, Unit(name))

    def addresses(self) -> list[str]:
        return [a for u in self.units.values() for a in u.addresses]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "disabled": self.disabled,
            "inactive": self.inactive,
            "lag": self.lag,
            "is_lag": self.is_lag,
            "mtu": self.mtu,
            "speed": self.speed,
            "protocols": sorted(self.protocols | {p for u in self.units.values() for p in u.protocols}),
            "units": [
                {
                    "name": u.name,
                    "description": u.description,
                    "vlan": u.vlan,
                    "addresses": u.addresses,
                    "switching": u.switching or None,
                    "protocols": sorted(u.protocols),
                    "disabled": u.disabled,
                    "vrf": u.vrf,
                }
                for u in sorted(self.units.values(), key=lambda u: (len(u.name), u.name))
            ],
        }


def is_virtual(name: str) -> bool:
    return bool(_JUNOS_VIRTUAL.match(name) or _IOS_VIRTUAL.match(name))


_SLOT = re.compile(r"(\d+(?:/\d+)+)")


def port_key(name: str) -> str:
    """Stable key for matching config interface names to device-type port names: the numeric
    slot/port part, without the Junos type prefix (et/xe/ge) or a channel suffix (``xe-0/0/0:2``).
    ``Ethernet1/1`` and ``Et1/1`` match; ``fxp0`` stays ``fxp0``."""
    base = name.split(":")[0].split(".")[0].strip()
    m = _SLOT.search(base)
    if not m:
        return base.lower()
    prefix = base[: m.start()].lower().rstrip("-")
    family = "eth" if prefix in ("et", "xe", "ge", "fe", "mge", "ethernet", "eth") or "ethernet" in prefix else prefix
    return f"{family}:{m.group(1)}"


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def parse_junos(config: str) -> dict[str, Interface]:
    ifs: dict[str, Interface] = {}
    ranges: dict[str, list[str]] = {}

    def get(name: str) -> Interface:
        return ifs.setdefault(name, Interface(name))

    for raw in config.splitlines():
        line = raw.strip()
        if line.startswith("deactivate interfaces "):
            t = _tokens(line)
            if len(t) == 3:
                get(t[2]).inactive = True
            continue
        if not line.startswith("set "):
            continue
        t = _tokens(line)[1:]
        ri = None
        if len(t) > 3 and t[0] == "routing-instances":
            ri = t[1]
            if t[2] == "interface":
                ifn, _, unit = t[3].partition(".")
                get(ifn).unit(unit or "0").vrf = ri
                continue
            t = t[2:]
        if len(t) >= 3 and t[0] == "interfaces":
            if t[1] == "interface-range" and len(t) > 4 and t[3] == "member":
                ranges.setdefault(t[2], []).append(t[4])
                continue
            i = get(t[1])
            rest = t[2:]
            key = rest[0]
            if key == "description":
                i.description = " ".join(rest[1:])
            elif key == "disable":
                i.disabled = True
            elif key == "mtu" and len(rest) > 1:
                i.mtu = _int(rest[1])
            elif key == "speed" and len(rest) > 1:
                i.speed = rest[1]
            elif key in ("gigether-options", "ether-options") and len(rest) > 2 and rest[1] == "802.3ad":
                i.lag = rest[2]
                get(rest[2])
            elif key == "unit" and len(rest) > 2:
                u = i.unit(rest[1])
                ur = rest[2:]
                if ur[0] == "description":
                    u.description = " ".join(ur[1:])
                elif ur[0] == "vlan-id" and len(ur) > 1:
                    u.vlan = _int(ur[1])
                elif ur[0] == "disable":
                    u.disabled = True
                elif ur[0] == "family" and len(ur) > 1:
                    fam = ur[1]
                    if len(ur) > 3 and ur[2] == "address":
                        u.addresses.append(ur[3])
                    elif fam in ("ethernet-switching", "bridge"):
                        if len(ur) > 3 and ur[2] in ("interface-mode", "port-mode"):
                            u.switching["mode"] = ur[3]
                        elif len(ur) > 4 and ur[2] == "vlan" and ur[3] == "members":
                            u.switching.setdefault("vlans", []).extend(x for x in ur[4:] if x not in "[]")
                        u.switching.setdefault("mode", u.switching.get("mode", "access"))
                    elif fam in ("mpls", "iso"):
                        u.protocols.add(fam)
        elif len(t) >= 3 and t[0] == "protocols" and ri is None:
            proto = t[1]
            if proto in ("ospf", "ospf3") and "interface" in t:
                _proto_on(ifs, t[t.index("interface") + 1], "ospf", get)
            elif proto in ("isis", "ldp", "mpls", "rsvp", "lldp", "pim", "bfd") and len(t) > 3 and t[2] == "interface":
                if t[3] != "all":
                    _proto_on(ifs, t[3], proto, get)
    # interface-range members are real ports even if only the range carries their config
    for members in ranges.values():
        for m in members:
            if "[" not in m and "-" in m:
                get(m)
    return ifs


def _proto_on(ifs: dict[str, Interface], name: str, proto: str, get) -> None:
    ifn, _, unit = name.partition(".")
    get(ifn).unit(unit or "0").protocols.add(proto)


def _mask_to_prefix(addr: str, mask: str) -> str:
    try:
        return str(ipaddress.ip_interface(f"{addr}/{mask}"))
    except ValueError:
        return addr


def parse_ios_like(config: str) -> dict[str, Interface]:
    ifs: dict[str, Interface] = {}
    cur: Interface | None = None
    cur_unit: Unit | None = None
    for raw in config.splitlines():
        if not raw.strip() or raw.strip().startswith("!"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent == 0:
            cur = cur_unit = None
            m = re.match(r"^interface (\S+(?: \d\S*)?)$", line)
            if m:
                full = m.group(1).replace(" ", "")
                parent, dot, sub = full.partition(".")
                cur = ifs.setdefault(parent, Interface(parent))
                cur_unit = cur.unit(sub if dot else "0")
            continue
        if cur is None or cur_unit is None:
            continue
        main = cur_unit.name == "0"
        if line.startswith("description "):
            if main:
                cur.description = line[12:]
            else:
                cur_unit.description = line[12:]
        elif line == "shutdown":
            if main:
                cur.disabled = True
            else:
                cur_unit.disabled = True
        elif m := re.match(r"^channel-group (\d+)", line):
            cur.lag = f"Port-Channel{m.group(1)}" if "Port-Channel" in config else f"Port-channel{m.group(1)}"
            ifs.setdefault(cur.lag, Interface(cur.lag))
        elif m := re.match(r"^mtu (\d+)", line):
            cur.mtu = int(m.group(1))
        elif m := re.match(r"^speed (\S+)", line):
            cur.speed = m.group(1)
        elif m := re.match(r"^ip address (\S+) (\d+\.\d+\.\d+\.\d+)", line):
            cur_unit.addresses.append(_mask_to_prefix(m.group(1), m.group(2)))
        elif m := re.match(r"^ip address (\S+/\d+)", line):
            cur_unit.addresses.append(m.group(1))
        elif m := re.match(r"^ipv6 address (\S+/\d+)", line):
            cur_unit.addresses.append(m.group(1))
        elif m := re.match(r"^encapsulation dot1[qQ] (\d+)", line):
            cur_unit.vlan = int(m.group(1))
        elif m := re.match(r"^(?:vrf forwarding|vrf member|vrf|ip vrf forwarding) (\S+)", line):
            cur_unit.vrf = m.group(1)
        elif m := re.match(r"^switchport mode (\S+)", line):
            cur_unit.switching["mode"] = m.group(1)
        elif m := re.match(r"^switchport access vlan (\S+)", line):
            cur_unit.switching.setdefault("mode", "access")
            cur_unit.switching["vlans"] = [m.group(1)]
        elif m := re.match(r"^switchport trunk allowed vlan (?:add )?(\S+)", line):
            cur_unit.switching.setdefault("mode", "trunk")
            cur_unit.switching.setdefault("vlans", []).extend(m.group(1).split(","))
        elif m := re.match(r"^ip (ospf|router isis)\b", line):
            cur_unit.protocols.add("ospf" if m.group(1) == "ospf" else "isis")
        elif line.startswith("mpls ip"):
            cur_unit.protocols.add("mpls")
    return ifs


# --- FortiOS -----------------------------------------------------------------------------------

_FORTI_VIRTUAL_TYPES = {"tunnel", "loopback", "vap-switch", "switch", "wl-mesh", "fext-wan", "ssl", "emac-vlan"}


def _forti_values(rest: str) -> list[str]:
    return _tokens(rest)


def parse_fortios(config: str) -> dict[str, Interface]:
    """``config system interface`` blocks of a FortiGate ``show`` (VDOM or global); VLAN interfaces
    become units of their parent port, aggregates are LAGs."""
    ifs: dict[str, Interface] = {}
    raw: dict[str, dict] = {}  # edit name -> {key: value(s)}, plus "ipv6" addresses
    depth = 0
    in_if = False
    if_depth = 0
    cur: dict | None = None
    for line in (ln.strip() for ln in config.splitlines()):
        if line.startswith("config "):
            depth += 1
            if line == "config system interface":
                in_if, if_depth = True, depth
            continue
        if line == "end":
            if in_if and depth == if_depth:
                in_if, cur = False, None
            depth = max(0, depth - 1)
            continue
        if not in_if:
            continue
        if line.startswith("edit ") and depth == if_depth:
            name = _forti_values(line[5:])[0] if line[5:].strip() else ""
            cur = raw.setdefault(name, {"_v6": []})
            continue
        if line == "next" and depth == if_depth:
            cur = None
            continue
        if cur is None or not line.startswith("set "):
            continue
        key, _, rest = line[4:].partition(" ")
        vals = _forti_values(rest)
        if depth > if_depth:  # inside "config ipv6" (or secondaryip) of the interface
            if key in ("ip6-address", "ip6-extra-addr") or (key == "ip" and len(vals) == 1 and ":" in vals[0]):
                cur["_v6"] += [v for v in vals if "/" in v and v != "::/0"]
            elif key == "ip" and len(vals) >= 2:
                cur.setdefault("_secondary", []).append(_mask_to_prefix(vals[0], vals[1]))
            continue
        cur[key] = vals
    for name, kv in raw.items():
        parent = (kv.get("interface") or [None])[0]
        vlan = _int((kv.get("vlanid") or [""])[0])
        if parent and vlan is not None:
            i = ifs.setdefault(parent, Interface(parent))
            u = i.unit(str(vlan))
            u.vlan = vlan
        else:
            i = ifs.setdefault(name, Interface(name))
            u = i.unit("0")
        desc = " ".join(kv.get("description") or []) or " ".join(kv.get("alias") or []) or None
        if u.name == "0":
            i.description = desc or i.description
            i.disabled = (kv.get("status") or [""])[0] == "down"
            if kv.get("speed"):
                i.speed = kv["speed"][0]
            if kv.get("mtu"):
                i.mtu = _int(kv["mtu"][0])
            itype = (kv.get("type") or [""])[0]
            if itype == "aggregate" or itype == "redundant":
                i.kind = "lag"
                for m in kv.get("member") or []:
                    ifs.setdefault(m, Interface(m)).lag = name
            elif itype in _FORTI_VIRTUAL_TYPES or name.startswith(("ssl.", "naf.", "l2t.", "npu", "modem")):
                i.kind = "virtual"
        else:
            u.description = desc
            u.disabled = (kv.get("status") or [""])[0] == "down"
        ip = kv.get("ip") or []
        if len(ip) >= 2 and ip[0] != "0.0.0.0":  # noqa: S104 - FortiOS's "no address"
            u.addresses.append(_mask_to_prefix(ip[0], ip[1]))
        u.addresses += kv.get("_secondary", []) + kv["_v6"]
        if kv.get("vrf"):
            u.vrf = kv["vrf"][0]
    return ifs


# --- RouterOS (/export terse) -----------------------------------------------------------------------


def _kv(text: str) -> dict[str, str]:
    out = {}
    for tok in _tokens(text):
        k, eq, v = tok.partition("=")
        if eq:
            out[k] = v
    return out


_ROS_VERBS = {"add", "set"}
_ROS_VIRTUAL = {"bridge", "eoip", "gre", "ipip", "l2tp-client", "pppoe-client", "wireguard", "vrrp", "veth", "vxlan"}


def parse_routeros(config: str) -> dict[str, Interface]:
    """``/export terse``: one command per line, ``/menu path verb [ find ... ] key=value ...``."""
    ifs: dict[str, Interface] = {}
    vlans: dict[str, tuple[str, str]] = {}  # vlan interface name -> (parent, vlan id)
    addresses: list[tuple[str, str]] = []

    def get(name: str) -> Interface:
        return ifs.setdefault(name, Interface(name))

    for line in (ln.strip() for ln in config.replace("\\\n", "").splitlines()):
        if not line.startswith("/"):
            continue
        default = re.search(r"\[\s*find\s+default-name=\"?([^\s\"\]]+)\"?\s*\]", line)
        words = re.sub(r"\[[^\]]*\]", " ", line).split()
        verb_at = next((n for n, w in enumerate(words) if w in _ROS_VERBS), None)
        if verb_at is None:
            continue
        menu = [w.lstrip("/") for w in words[:verb_at]]
        kv = _kv(" ".join(words[verb_at + 1 :]))
        if menu[:1] == ["interface"]:
            sub = menu[1] if len(menu) > 1 else ""
            name = kv.get("name") or (default.group(1) if default else None)
            if not name:
                continue
            if sub == "vlan":
                parent, vid = kv.get("interface", name), kv.get("vlan-id", "0")
                vlans[name] = (parent, vid)
                u = get(parent).unit(vid)
                u.vlan = _int(vid)
                u.description = kv.get("comment") or u.description
                u.disabled = kv.get("disabled") == "yes"
                continue
            if sub == "list":
                continue
            i = get(name)
            i.description = kv.get("comment") or i.description
            i.disabled = kv.get("disabled") == "yes" or i.disabled
            if kv.get("mtu"):
                i.mtu = _int(kv["mtu"])
            if sub == "bonding":
                i.kind = "lag"
                for m in kv.get("slaves", "").split(","):
                    if m:
                        get(m).lag = name
            elif sub in _ROS_VIRTUAL:
                i.kind = "virtual"
        elif menu[:2] in (["ip", "address"], ["ipv6", "address"]) and kv.get("disabled") != "yes":
            addresses.append((kv.get("interface", ""), kv.get("address", "")))
    for ifname, addr in addresses:
        if ifname and addr:
            parent, unit = vlans.get(ifname, (ifname, "0"))
            get(parent).unit(unit).addresses.append(addr if "/" in addr else f"{addr}/32")
    return ifs


# --- VyOS (show configuration commands) ---------------------------------------------------------------

_VYOS_VIRTUAL = {"loopback", "tunnel", "wireguard", "vti", "dummy", "bridge", "openvpn", "pppoe", "l2tpv3", "vxlan"}


def parse_vyos(config: str) -> dict[str, Interface]:
    ifs: dict[str, Interface] = {}

    def get(name: str) -> Interface:
        return ifs.setdefault(name, Interface(name))

    for line in (ln.strip() for ln in config.splitlines()):
        if not line.startswith("set interfaces "):
            continue
        t = _tokens(line)[2:]
        if len(t) < 3:
            continue
        itype, name, rest = t[0], t[1], t[2:]
        i = get(name)
        if itype == "bonding":
            i.kind = "lag"
        elif itype in _VYOS_VIRTUAL:
            i.kind = "virtual"
        u = i.unit("0")
        if rest[0] in ("vif", "vif-s") and len(rest) > 2:
            u = i.unit(rest[1])
            u.vlan = _int(rest[1])
            rest = rest[2:]
        key = rest[0]
        if key == "description" and len(rest) > 1:
            if u.name == "0":
                i.description = " ".join(rest[1:])
            else:
                u.description = " ".join(rest[1:])
        elif key == "disable":
            if u.name == "0":
                i.disabled = True
            else:
                u.disabled = True
        elif key == "address" and len(rest) > 1 and "/" in rest[1]:
            u.addresses.append(rest[1])
        elif key == "mtu" and len(rest) > 1:
            i.mtu = _int(rest[1])
        elif key == "bond-group" and len(rest) > 1:
            i.lag = rest[1]
            get(rest[1]).kind = "lag"
        elif key == "member" and len(rest) > 2 and rest[1] == "interface":
            get(rest[2]).lag = name
        elif key == "vrf" and len(rest) > 1:
            u.vrf = rest[1]
    return ifs


def parse(config: str, platform: str | None) -> dict[str, Interface]:
    if platform == "junos" or (platform is None and "\nset interfaces " in config and " unit " in config):
        return parse_junos(config)
    if platform == "fortios" or (platform is None and "config system interface" in config):
        return parse_fortios(config)
    if platform == "routeros" or (platform is None and "\n/ip address add" in config):
        return parse_routeros(config)
    if platform == "vyos" or (platform is None and "\nset interfaces ethernet " in config):
        return parse_vyos(config)
    if platform in ("ios", "eos", "nxos", "iosxr") or (platform is None and "\ninterface " in config):
        return parse_ios_like(config)
    return {}


def _int(v: str) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
