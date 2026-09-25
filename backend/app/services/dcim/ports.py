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
_LAG = re.compile(r"^(ae\d+|reth\d+|port-channel\s*\d+|bundle-ether\d+|po\d+)$", re.I)


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

    @property
    def is_lag(self) -> bool:
        return bool(_LAG.match(self.name))

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


def parse(config: str, platform: str | None) -> dict[str, Interface]:
    if platform == "junos" or (platform is None and "\nset interfaces " in config):
        return parse_junos(config)
    if platform in ("ios", "eos", "nxos") or (platform is None and "\ninterface " in config):
        return parse_ios_like(config)
    return {}


def _int(v: str) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
