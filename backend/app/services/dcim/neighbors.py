"""LLDP neighbours: the commands that list them per platform and parsers for their output.

The commands run in the same SSH session as the configuration backup, after it, and are best
effort: a device without LLDP (or a command the box rejects) simply reports no neighbours. Junos,
EOS and NX-OS answer in JSON; IOS / IOS-XE detail output and RouterOS ``/ip neighbor`` are text.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

# platform slug -> commands (override per tenant with backup settings ``neighbor_commands``)
NEIGHBOR_COMMANDS: dict[str, list[str]] = {
    "junos": ["show lldp neighbors | display json | no-more"],
    "eos": ["show lldp neighbors detail | json"],
    "nxos": ["show lldp neighbors detail | json"],
    "ios": ["show lldp neighbors detail"],
    "routeros": ["/ip neighbor print detail terse without-paging"],
}


@dataclass
class Neighbor:
    local_interface: str
    remote_system: str | None = None
    remote_port: str | None = None
    remote_port_description: str | None = None
    remote_chassis: str | None = None
    remote_address: str | None = None
    protocol: str = "lldp"

    def to_dict(self) -> dict:
        return asdict(self)


def _json(text: str):
    """The JSON document in command output: devices echo prompts ("{master:0}") and the command
    around it, so decode from each "{" until one parses to an object."""
    dec = json.JSONDecoder()
    pos = text.find("{")
    while pos >= 0:
        try:
            doc, _ = dec.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(doc, dict):
            return doc
        pos = text.find("{", pos + 1)
    return None


def _clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


# --- Junos -----------------------------------------------------------------------------------------


def _jdata(item: dict, *keys: str) -> str | None:
    for k in keys:
        v = item.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return _clean(v[0].get("data"))
        if isinstance(v, str):
            return _clean(v)
    return None


def parse_junos(text: str) -> list[Neighbor]:
    doc = _json(text)
    if doc is None:
        return parse_junos_text(text)
    out = []
    for info in doc.get("lldp-neighbors-information", []) or []:
        for item in info.get("lldp-neighbor-information", []) or []:
            local = _jdata(item, "lldp-local-port-id", "lldp-local-interface")
            if not local:
                continue
            out.append(
                Neighbor(
                    local_interface=local,
                    remote_system=_jdata(item, "lldp-remote-system-name"),
                    remote_port=_jdata(item, "lldp-remote-port-id"),
                    remote_port_description=_jdata(item, "lldp-remote-port-description"),
                    remote_chassis=_jdata(item, "lldp-remote-chassis-id"),
                    remote_address=_jdata(item, "lldp-remote-management-address"),
                )
            )
    return out


def parse_junos_text(text: str) -> list[Neighbor]:
    """``show lldp neighbors`` table (columns found from the header line)."""
    lines = text.splitlines()
    head = next((n for n, ln in enumerate(lines) if ln.startswith("Local Interface")), None)
    if head is None:
        return []
    hdr = lines[head]
    cols = [hdr.find(c) for c in ("Local Interface", "Parent Interface", "Chassis Id", "Port info", "System Name")]
    if min(cols) < 0:
        return []
    out = []
    for ln in lines[head + 1 :]:
        if not ln.strip() or ln.startswith("{"):
            continue
        parts = ln.split()
        if len(parts) == 5:
            local, _parent, chassis, port, system = parts
        else:
            local = ln[cols[0] : cols[1]].strip()
            chassis = ln[cols[2] : cols[3]].strip()
            port = ln[cols[3] : cols[4]].strip()
            system = ln[cols[4] :].strip()
        if local:
            out.append(Neighbor(local, _clean(system), _clean(port), None, _clean(chassis)))
    return out


# --- EOS / NX-OS ------------------------------------------------------------------------------------


def parse_eos(text: str) -> list[Neighbor]:
    doc = _json(text) or {}
    out = []
    nbrs = doc.get("lldpNeighbors")
    if isinstance(nbrs, list):  # "show lldp neighbors | json"
        for n in nbrs:
            if n.get("port"):
                out.append(Neighbor(n["port"], _clean(n.get("neighborDevice")), _clean(n.get("neighborPort"))))
        return out
    if isinstance(nbrs, dict):  # "show lldp neighbors detail | json"
        for port, info in nbrs.items():
            for n in info.get("lldpNeighborInfo", []) or []:
                pid = n.get("neighborInterfaceInfo") or {}
                mgmt = (n.get("managementAddresses") or [{}])[0] if n.get("managementAddresses") else {}
                out.append(
                    Neighbor(
                        port,
                        _clean(n.get("systemName")),
                        _clean(pid.get("interfaceId_v2") or pid.get("interfaceId")),
                        _clean(pid.get("interfaceDescription")),
                        _clean(n.get("chassisId")),
                        _clean(mgmt.get("address")),
                    )
                )
    return out


def parse_nxos(text: str) -> list[Neighbor]:
    doc = _json(text) or {}
    rows = (doc.get("TABLE_nbor_detail") or {}).get("ROW_nbor_detail") or []
    if isinstance(rows, dict):
        rows = [rows]
    return [
        Neighbor(
            r["l_port_id"],
            _clean(r.get("sys_name")),
            _clean(r.get("port_id")),
            _clean(r.get("port_desc")),
            _clean(r.get("chassis_id")),
            _clean(r.get("mgmt_addr")),
        )
        for r in rows
        if r.get("l_port_id")
    ]


# --- IOS / IOS-XE (text) ---------------------------------------------------------------------------


def parse_ios(text: str) -> list[Neighbor]:
    out = []
    for block in re.split(r"\n-{10,}\s*\n", "\n" + text):
        fields: dict[str, str] = {}
        for ln in block.splitlines():
            m = re.match(r"^\s*(Local Intf|Chassis id|Port id|Port Description|System Name)\s*:\s*(.*)$", ln)
            if m:
                fields.setdefault(m.group(1), m.group(2).strip())
            elif (m := re.match(r"^\s*IP(?:v4)?(?: address)?\s*:\s*(\S+)", ln)) and "addr" not in fields:
                fields["addr"] = m.group(1)
        if fields.get("Local Intf"):
            out.append(
                Neighbor(
                    fields["Local Intf"],
                    _clean(fields.get("System Name")),
                    _clean(fields.get("Port id")),
                    _clean(fields.get("Port Description")),
                    _clean(fields.get("Chassis id")),
                    _clean(fields.get("addr")),
                )
            )
    return out


# --- RouterOS ----------------------------------------------------------------------------------------


def parse_routeros(text: str) -> list[Neighbor]:
    out = []
    for ln in text.splitlines():
        kv = dict(m.groups() for m in re.finditer(r'([\w-]+)=("[^"]*"|\S*)', ln))
        kv = {k: v.strip('"') for k, v in kv.items()}
        if not kv.get("interface"):
            continue
        local = kv["interface"].split(",")[0]
        out.append(
            Neighbor(
                local,
                _clean(kv.get("identity") or kv.get("system-description")),
                _clean(kv.get("interface-name")),
                None,
                _clean(kv.get("mac-address")),
                _clean(kv.get("address") or kv.get("address4")),
                "lldp" if "lldp" in kv.get("discovered-by", "lldp") else kv.get("discovered-by", "mndp"),
            )
        )
    return out


PARSERS = {"junos": parse_junos, "eos": parse_eos, "nxos": parse_nxos, "ios": parse_ios, "routeros": parse_routeros}


def parse(text: str, platform: str | None) -> list[Neighbor]:
    fn = PARSERS.get(platform or "")
    if fn is None or not text:
        return []
    seen = set()
    out = []
    for n in fn(text):
        key = (n.local_interface, n.remote_system, n.remote_port, n.remote_chassis)
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out
