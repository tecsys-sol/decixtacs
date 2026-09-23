"""Configuration intelligence: parse configs into searchable objects.

Supports Junos ``display set`` output (primary: ISP/IXP core) and Cisco/Arista style
hierarchical configs (``router bgp``, ``ip prefix-list``, ``ip community-list`` ...).

Examples enabled by the index:
* all devices using community 65000:100    -> kind=community, attributes.members contains
* all BGP neighbours with ASN 13335        -> kind=bgp_neighbor, attributes.peer_as == 13335
* all devices containing prefix-list XYZ   -> kind=prefix_list, key == XYZ
"""

from __future__ import annotations

import re
import shlex
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class IndexObject:
    kind: str
    key: str
    attributes: dict = field(default_factory=dict)


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def parse_junos_set(config: str) -> list[IndexObject]:
    interfaces: dict[str, dict] = defaultdict(lambda: {"units": {}, "description": None})
    groups: dict[tuple[str, str], dict] = {}
    neighbors: dict[tuple[str, str, str], dict] = {}
    communities: dict[str, dict] = defaultdict(lambda: {"members": []})
    prefix_lists: dict[str, dict] = defaultdict(lambda: {"prefixes": []})
    filters: dict[str, dict] = defaultdict(lambda: {"terms": set(), "family": None})
    policies: dict[str, dict] = defaultdict(lambda: {"terms": set(), "communities": set(), "prefix_lists": set()})
    instances: dict[str, dict] = defaultdict(lambda: {"type": None, "interfaces": [], "rd": None})

    for raw in config.splitlines():
        line = raw.strip()
        if not line.startswith("set "):
            continue
        t = _tokens(line)[1:]
        if not t:
            continue
        ri = "master"
        if t[0] == "routing-instances" and len(t) > 2:
            ri = t[1]
            inst = instances[ri]
            if t[2] == "instance-type" and len(t) > 3:
                inst["type"] = t[3]
            elif t[2] == "interface" and len(t) > 3:
                inst["interfaces"].append(t[3])
            elif t[2] == "route-distinguisher" and len(t) > 3:
                inst["rd"] = t[3]
            t = t[2:]
        if t[0] == "interfaces" and len(t) > 2:
            ifd = interfaces[t[1]]
            if t[2] == "description":
                ifd["description"] = " ".join(t[3:])
            elif t[2] == "unit" and len(t) > 3:
                unit = ifd["units"].setdefault(t[3], {"vlan": None, "addresses": [], "description": None})
                rest = t[4:]
                if rest[:1] == ["vlan-id"] and len(rest) > 1:
                    unit["vlan"] = rest[1]
                elif rest[:1] == ["description"]:
                    unit["description"] = " ".join(rest[1:])
                elif len(rest) >= 4 and rest[0] == "family" and rest[2] == "address":
                    unit["addresses"].append(rest[3])
        elif t[0] == "protocols" and len(t) > 3 and t[1] == "bgp" and t[2] == "group":
            gname = t[3]
            grp = groups.setdefault(
                (ri, gname),
                {"routing_instance": ri, "type": None, "peer_as": None, "import": [], "export": [], "neighbors": 0},
            )
            rest = t[4:]
            if rest[:1] == ["type"] and len(rest) > 1:
                grp["type"] = rest[1]
            elif rest[:1] == ["peer-as"] and len(rest) > 1:
                grp["peer_as"] = _int(rest[1])
            elif rest[:1] in (["import"], ["export"]) and len(rest) > 1:
                grp[rest[0]].extend(x for x in rest[1:] if x not in "[]")
            elif rest[:1] == ["neighbor"] and len(rest) > 1:
                nkey = (ri, gname, rest[1])
                nb = neighbors.setdefault(
                    nkey,
                    {
                        "group": gname,
                        "routing_instance": ri,
                        "peer_as": None,
                        "description": None,
                        "import": [],
                        "export": [],
                    },
                )
                nrest = rest[2:]
                if nrest[:1] == ["peer-as"] and len(nrest) > 1:
                    nb["peer_as"] = _int(nrest[1])
                elif nrest[:1] == ["description"]:
                    nb["description"] = " ".join(nrest[1:])
                elif nrest[:1] in (["import"], ["export"]) and len(nrest) > 1:
                    nb[nrest[0]].extend(x for x in nrest[1:] if x not in "[]")
        elif t[0] == "policy-options" and len(t) > 2:
            if t[1] == "community" and len(t) > 3 and t[3] == "members":
                communities[t[2]]["members"].extend(x for x in t[4:] if x not in "[]")
            elif t[1] == "prefix-list" and len(t) > 3:
                prefix_lists[t[2]]["prefixes"].append(t[3])
            elif t[1] == "prefix-list":
                prefix_lists[t[2]]
            elif t[1] == "policy-statement" and len(t) > 2:
                pol = policies[t[2]]
                if len(t) > 4 and t[3] == "term":
                    pol["terms"].add(t[4])
                if "community" in t:
                    i = t.index("community")
                    if i + 1 < len(t) and t[i + 1] not in ("add", "set", "delete"):
                        pol["communities"].add(t[i + 1])
                    elif i + 2 < len(t):
                        pol["communities"].add(t[i + 2])
                if "prefix-list" in t or "prefix-list-filter" in t:
                    i = t.index("prefix-list") if "prefix-list" in t else t.index("prefix-list-filter")
                    if i + 1 < len(t):
                        pol["prefix_lists"].add(t[i + 1])
        elif t[0] == "firewall":
            rest = t[1:]
            fam = None
            if rest[:1] == ["family"] and len(rest) > 1:
                fam, rest = rest[1], rest[2:]
            if rest[:1] == ["filter"] and len(rest) > 1:
                f = filters[rest[1]]
                f["family"] = fam
                if len(rest) > 3 and rest[2] == "term":
                    f["terms"].add(rest[3])

    out: list[IndexObject] = []
    for name, d in interfaces.items():
        out.append(IndexObject("interface", name, {"description": d["description"], "units": d["units"]}))
        for unit, u in d["units"].items():
            if u["vlan"]:
                out.append(IndexObject("vlan", str(u["vlan"]), {"interface": f"{name}.{unit}", **u}))
    for ri, gname, _addr in neighbors:
        if (ri, gname) in groups:
            groups[(ri, gname)]["neighbors"] += 1
    for (_ri, gname), g in groups.items():
        out.append(IndexObject("bgp_group", gname, g))
    for (ri, gname, addr), nb in neighbors.items():
        if nb["peer_as"] is None:
            nb["peer_as"] = groups.get((ri, gname), {}).get("peer_as")
        out.append(IndexObject("bgp_neighbor", addr, nb))
    for name, c in communities.items():
        out.append(IndexObject("community", name, c))
        for m in c["members"]:
            out.append(IndexObject("community_value", m, {"community": name}))
    for name, p in prefix_lists.items():
        out.append(IndexObject("prefix_list", name, p))
    for name, f in filters.items():
        out.append(IndexObject("firewall_filter", name, {"family": f["family"], "terms": sorted(f["terms"])}))
    for name, p in policies.items():
        out.append(IndexObject("policy", name, {k: sorted(v) for k, v in p.items()}))
    for name, i in instances.items():
        out.append(IndexObject("routing_instance", name, i))
    return out


def parse_ios_like(config: str) -> list[IndexObject]:
    """Cisco IOS/NX-OS and Arista EOS."""
    out: list[IndexObject] = []
    local_as = None
    vrf = "default"
    current_if: str | None = None
    neighbors: dict[tuple[str, str], dict] = {}
    peer_groups: dict[str, dict] = {}
    prefix_lists: dict[str, list] = defaultdict(list)
    for raw in config.splitlines():
        if not raw.strip() or raw.strip().startswith("!"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent == 0:
            current_if = None
            if m := re.match(r"^router bgp (\d+)", line):
                local_as, vrf = int(m.group(1)), "default"
            elif m := re.match(r"^interface (\S+)", line):
                current_if = m.group(1)
                out.append(IndexObject("interface", current_if, {}))
            elif m := re.match(r"^ip(?:v6)? prefix-list (\S+) (?:seq \d+ )?(permit|deny) (\S+)", line):
                prefix_lists[m.group(1)].append(f"{m.group(2)} {m.group(3)}")
            elif m := re.match(r"^ip(?:v6)? prefix-list (\S+)$", line):
                prefix_lists[m.group(1)]
            elif m := re.match(r"^ip community-list (?:standard |expanded )?(\S+) (permit|deny) (.+)$", line):
                name = m.group(1)
                members = m.group(3).split()
                out.append(IndexObject("community", name, {"members": members}))
                out += [IndexObject("community_value", v, {"community": name}) for v in members]
            elif m := re.match(r"^route-map (\S+)", line):
                out.append(IndexObject("policy", m.group(1), {}))
            elif m := re.match(r"^(?:ip )?access-list (?:extended |standard )?(\S+)", line):
                out.append(IndexObject("firewall_filter", m.group(1), {}))
            elif m := re.match(r"^vlan (\d+)", line):
                out.append(IndexObject("vlan", m.group(1), {}))
            elif m := re.match(r"^vrf (?:definition|instance) (\S+)", line):
                out.append(IndexObject("routing_instance", m.group(1), {}))
            continue
        if local_as is not None and (m := re.match(r"^vrf (\S+)", line)):
            vrf = m.group(1)
        elif local_as is not None and (
            m := re.match(r"^neighbor (\S+) (remote-as|peer group|peer-group|description) ?(.*)$", line)
        ):
            addr, attr, val = m.groups()
            if attr == "remote-as":
                nb = neighbors.setdefault((vrf, addr), {"routing_instance": vrf, "local_as": local_as})
                nb["peer_as"] = _int(val)
            elif attr in ("peer group", "peer-group") and not val:
                peer_groups.setdefault(addr, {})
            elif attr in ("peer group", "peer-group"):
                neighbors.setdefault((vrf, addr), {"routing_instance": vrf, "local_as": local_as})["group"] = val
            elif attr == "description":
                neighbors.setdefault((vrf, addr), {"routing_instance": vrf, "local_as": local_as})["description"] = val
    for (_vrf, addr), nb in neighbors.items():
        if addr in peer_groups:
            out.append(IndexObject("bgp_group", addr, nb))
        else:
            out.append(IndexObject("bgp_neighbor", addr, nb))
    out += [IndexObject("prefix_list", n, {"prefixes": p}) for n, p in prefix_lists.items()]
    return out


def parse(config: str, platform: str) -> list[IndexObject]:
    if platform == "junos":
        return parse_junos_set(config)
    if platform in ("ios", "eos", "nxos"):
        return parse_ios_like(config)
    return []


def _int(v: str) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
