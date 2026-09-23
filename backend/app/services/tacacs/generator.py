"""Module 2 - render a complete tac_plus-ng configuration from the database.

Administrators never edit tac_plus-ng.cfg by hand: every change goes through the API, is audited,
rendered here, validated on the TACACS host with ``tac_plus-ng -P`` by the agent and then reloaded.

The renderer works on plain dataclasses so it is independent from the ORM and easy to unit-test.

Vendor handling
---------------
* Cisco IOS/NX-OS, Arista EOS, Sophos SFOS: ``service = shell`` with ``priv-lvl`` and per-command
  authorization (``cmd =~ /regex/``).
* Juniper Junos: ``service = junos-exec`` returning ``local-user-name`` (template user/class on the
  box) plus ``allow-commands`` / ``deny-commands`` regexes, which Junos enforces locally.
* Fortinet FortiOS: ``service = fortigate`` returning ``admin_prof`` (+ ``memberof``).
* MikroTik RouterOS has no TACACS+ client (RADIUS only). Such NAS entries are emitted as comments
  and reported as warnings so nobody believes they are protected.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

Action = Literal["permit", "deny"]

_IDENT = re.compile(r"[^A-Za-z0-9_.-]+")


def ident(name: str) -> str:
    """tac_plus-ng object names: keep them to a safe character set."""
    cleaned = _IDENT.sub("-", name.strip()).strip("-")
    return cleaned or "unnamed"


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def regex_literal(pattern: str) -> str:
    return "/" + pattern.replace("/", "\\/") + "/"


@dataclass
class NasEntry:
    name: str
    address: str
    key: str
    vendor: str
    tags: list[str] = field(default_factory=list)


@dataclass
class CommandRule:
    action: Action
    pattern: str
    sequence: int = 10


@dataclass
class Profile:
    name: str
    group: str
    priority: int = 100
    privilege_level: int = 1
    device_tags: list[str] = field(default_factory=list)  # empty = all devices
    commands: list[CommandRule] = field(default_factory=list)
    default_action: Action = "deny"
    junos_class: str | None = None
    fortigate_profile: str | None = None
    arista_role: str | None = None
    extra_attributes: dict[str, dict[str, str]] = field(default_factory=dict)
    timespan: str | None = None  # cron-like "* 8-20 * * 1-5"


@dataclass
class TacUser:
    username: str
    groups: list[str]
    auth_method: Literal["crypt", "ldap"] = "crypt"
    password_crypt: str | None = None
    valid_until: str | None = None  # YYYY-MM-DD


@dataclass
class LdapBackend:
    server_type: str  # "microsoft" | "generic" | "tacacs_schema"
    hosts: str
    base: str
    bind_dn: str
    bind_password: str
    group_prefix: str = ""


@dataclass
class ServerSettings:
    listen_port: int = 49
    access_log: str = "/var/log/tac_plus-ng/access.log"
    authz_log: str = "/var/log/tac_plus-ng/authz.log"
    acct_log: str = "/var/log/tac_plus-ng/acct.log"
    syslog_host: str | None = None
    instances_max: int = 32
    ldap: LdapBackend | None = None


@dataclass
class RenderResult:
    content: str
    sha256: str
    warnings: list[str]


NO_TACACS_VENDORS = {"mikrotik"}


def _shell_block(p: Profile, indent: str) -> list[str]:
    lines = [f"{indent}if (service == shell) {{"]
    lines += [f'{indent}\tif (cmd == "") {{', f"{indent}\t\tset priv-lvl = {p.privilege_level}"]
    if p.arista_role:
        lines.append(f"{indent}\t\tset roles = {quote(p.arista_role)}")
    for attr, val in p.extra_attributes.get("shell", {}).items():
        lines.append(f"{indent}\t\tset {attr} = {quote(val)}")
    lines += [f"{indent}\t\tpermit", f"{indent}\t}}"]
    for rule in sorted(p.commands, key=lambda r: r.sequence):
        lines.append(f"{indent}\tif (cmd =~ {regex_literal(rule.pattern)}) {rule.action}")
    lines.append(f"{indent}\t{p.default_action}")
    lines.append(f"{indent}}}")
    return lines


def _junos_block(p: Profile, indent: str) -> list[str]:
    allow = [r.pattern for r in sorted(p.commands, key=lambda r: r.sequence) if r.action == "permit"]
    deny = [r.pattern for r in sorted(p.commands, key=lambda r: r.sequence) if r.action == "deny"]
    lines = [f"{indent}if (service == junos-exec) {{"]
    local_user = p.junos_class or ("remote-su" if p.privilege_level >= 15 else "remote-ro")
    lines.append(f"{indent}\tset local-user-name = {quote(local_user)}")
    if allow and p.default_action == "deny":
        lines.append(f"{indent}\tset allow-commands = {quote('|'.join(f'({a})' for a in allow))}")
    if deny:
        lines.append(f"{indent}\tset deny-commands = {quote('|'.join(f'({d})' for d in deny))}")
    for attr, val in p.extra_attributes.get("juniper", {}).items():
        lines.append(f"{indent}\tset {attr} = {quote(val)}")
    lines += [f"{indent}\tpermit", f"{indent}}}"]
    return lines


def _fortigate_block(p: Profile, indent: str) -> list[str]:
    prof = p.fortigate_profile or ("super_admin" if p.privilege_level >= 15 else "prof_admin_readonly")
    lines = [f"{indent}if (service == fortigate) {{", f"{indent}\tset admin_prof = {quote(prof)}"]
    lines.append(f"{indent}\tset memberof = {quote(p.group)}")
    for attr, val in p.extra_attributes.get("fortinet", {}).items():
        lines.append(f"{indent}\tset {attr} = {quote(val)}")
    lines += [f"{indent}\tpermit", f"{indent}}}"]
    return lines


def render_profile(p: Profile) -> list[str]:
    name = ident(p.name)
    out = [f"\tprofile {name} {{", "\t\tscript {"]
    out += _junos_block(p, "\t\t\t")
    out += _fortigate_block(p, "\t\t\t")
    out += _shell_block(p, "\t\t\t")
    out += ["\t\t\tdeny", "\t\t}", "\t}"]
    return out


def _rule_condition(p: Profile) -> str:
    cond = f"member == {ident(p.group)}"
    if p.device_tags:
        tag_expr = " || ".join(f"device.tag == {ident(t)}" for t in sorted(p.device_tags))
        cond += f" && ({tag_expr})" if len(p.device_tags) > 1 else f" && {tag_expr}"
    if p.timespan:
        cond += f" && time == ts-{ident(p.name)}"
    return cond


def render(
    nas: list[NasEntry],
    profiles: list[Profile],
    users: list[TacUser],
    settings: ServerSettings | None = None,
    header: str = "",
) -> RenderResult:
    s = settings or ServerSettings()
    warnings: list[str] = []
    lines: list[str] = []
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Generated by NetworkOps Manager - DO NOT EDIT. Changes are overwritten.")
    if header:
        lines += [f"# {h}" for h in header.splitlines()]
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("id = spawnd {")
    lines.append(f"\tlisten = {{ port = {s.listen_port} }}")
    lines.append(f"\tspawn = {{ instances min = 1 instances max = {s.instances_max} }}")
    lines.append("\tbackground = no")
    lines.append("}")
    lines.append("")
    lines.append("id = tac_plus-ng {")
    lines.append(f"\tlog accesslog {{ destination = {s.access_log} }}")
    lines.append(f"\tlog authzlog {{ destination = {s.authz_log} }}")
    lines.append(f"\tlog acctlog {{ destination = {s.acct_log} }}")
    if s.syslog_host:
        lines.append(f"\tlog netsyslog {{ destination = {s.syslog_host} }}")
    lines.append("\tauthentication log = accesslog")
    lines.append("\tauthorization log = authzlog")
    lines.append("\taccounting log = acctlog")
    if s.syslog_host:
        lines += ["\taccounting log = netsyslog", "\tauthorization log = netsyslog"]
    lines.append("")

    if s.ldap:
        ld = s.ldap
        lines += [
            "\tmavis module = external {",
            f"\t\tsetenv LDAP_SERVER_TYPE = {quote(ld.server_type)}",
            f"\t\tsetenv LDAP_HOSTS = {quote(ld.hosts)}",
            f"\t\tsetenv LDAP_BASE = {quote(ld.base)}",
            f"\t\tsetenv LDAP_USER = {quote(ld.bind_dn)}",
            f"\t\tsetenv LDAP_PASSWD = {quote(ld.bind_password)}",
            f"\t\tsetenv TACACS_GROUP_PREFIX = {quote(ld.group_prefix)}",
            "\t\texec = /usr/local/lib/mavis/mavis_tacplus-ng_ldap.pl",
            "\t}",
            "\tuser backend = mavis",
            "\tlogin backend = mavis",
            "\tpap backend = mavis",
            "",
        ]

    # --- NAS clients ---------------------------------------------------------
    for n in sorted(nas, key=lambda x: ident(x.name)):
        if n.vendor in NO_TACACS_VENDORS:
            warnings.append(f"{n.name}: vendor '{n.vendor}' has no TACACS+ client - use RADIUS; entry skipped")
            lines.append(f"\t# SKIPPED {ident(n.name)} ({n.address}): {n.vendor} does not support TACACS+")
            continue
        lines.append(f"\tdevice {ident(n.name)} {{")
        lines.append(f"\t\taddress = {n.address}")
        lines.append(f"\t\tkey = {quote(n.key)}")
        for t in sorted(set(n.tags)):
            lines.append(f"\t\ttag = {ident(t)}")
        lines.append("\t}")
    lines.append("")

    # --- time spans ----------------------------------------------------------
    for p in profiles:
        if p.timespan:
            lines.append(f"\ttimespan ts-{ident(p.name)} {{ {quote(p.timespan)} }}")

    # --- groups / users ------------------------------------------------------
    groups = sorted({ident(g) for p in profiles for g in [p.group]} | {ident(g) for u in users for g in u.groups})
    for g in groups:
        lines.append(f"\tgroup {g}")
    lines.append("")
    for u in sorted(users, key=lambda x: x.username):
        lines.append(f"\tuser {ident(u.username)} {{")
        if u.auth_method == "crypt":
            if not u.password_crypt:
                warnings.append(f"user {u.username}: no password set - login disabled")
                lines.append("\t\tpassword login = deny")
            else:
                lines.append(f"\t\tpassword login = crypt {u.password_crypt}")
        else:
            lines.append("\t\tpassword login = mavis")
        for g in sorted({ident(g) for g in u.groups}):
            lines.append(f"\t\tmember = {g}")
        if u.valid_until:
            lines.append(f"\t\tvalid until = {u.valid_until}")
        lines.append("\t}")
    lines.append("")

    # --- profiles + ruleset --------------------------------------------------
    ordered = sorted(profiles, key=lambda p: (p.priority, ident(p.name)))
    for p in ordered:
        lines += render_profile(p)
    lines.append("")
    lines.append("\truleset {")
    for p in ordered:
        lines.append(f"\t\trule {ident(p.name)} {{")
        lines.append("\t\t\tscript {")
        lines.append(f"\t\t\t\tif ({_rule_condition(p)}) {{ profile = {ident(p.name)} permit }}")
        lines.append("\t\t\t}")
        lines.append("\t\t}")
    lines.append("\t}")
    lines.append("}")
    content = "\n".join(lines) + "\n"
    return RenderResult(content=content, sha256=hashlib.sha256(content.encode()).hexdigest(), warnings=warnings)


def redact_keys(content: str) -> str:
    """Remove NAS keys and LDAP passwords before a render is stored or shown in the UI."""
    content = re.sub(r'(\bkey = )"(?:[^"\\]|\\.)*"', r'\1"***"', content)
    return re.sub(r'(LDAP_PASSWD = )"(?:[^"\\]|\\.)*"', r'\1"***"', content)
