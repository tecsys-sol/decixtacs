"""AI-assisted change analysis (phase 1: deterministic heuristics).

Scores a config diff 0-100, flags dangerous commands and produces a plain-English summary.
The interface (``analyse_diff`` -> ``RiskReport``) is what a future LLM-backed analyser plugs into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (regex on a removed(-) or added(+) line, weight, explanation)
DANGEROUS: list[tuple[str, str, int, str]] = [
    ("-", r"^set protocols bgp group \S+ neighbor", 25, "BGP neighbour removed"),
    ("-", r"^set protocols bgp", 15, "BGP configuration removed"),
    ("+", r"^(delete|deactivate) protocols bgp", 35, "BGP deleted/deactivated"),
    ("-", r"^\s*neighbor \S+ remote-as", 25, "BGP neighbour removed"),
    ("+", r"^no router bgp", 50, "BGP process removed"),
    ("-", r"^set firewall (family \S+ )?filter", 20, "Firewall filter term removed"),
    ("-", r"^set policy-options (policy-statement|prefix-list)", 15, "Routing policy removed"),
    ("-", r"^set interfaces \S+ unit \d+ family inet address", 15, "Interface address removed"),
    ("+", r"^set interfaces \S+ disable", 20, "Interface disabled"),
    ("+", r"^\s*shutdown$", 20, "Interface shut down"),
    ("-", r"^set system (login|authentication-order|tacplus-server)", 30, "AAA/login config removed"),
    ("-", r"^(aaa |tacacs-server|tacacs server)", 30, "AAA/TACACS config removed"),
    ("+", r"^set system services (telnet|ftp)", 25, "Insecure management service enabled"),
    ("+", r"snmp.*community (public|private)", 25, "Default SNMP community"),
    ("-", r"^set snmp", 5, "SNMP config removed"),
    ("-", r"^set routing-options (static|rib)", 10, "Static routing changed"),
    ("-", r"^\s*ip route ", 10, "Static route removed"),
    ("+", r"^(set )?.*\b(0\.0\.0\.0/0|::/0)\b.*(accept|permit)", 15, "Default route/permit-any added"),
    ("-", r"^set protocols (ospf|isis|mpls|ldp|rsvp)", 20, "IGP/MPLS config removed"),
]

DANGEROUS_COMMANDS: list[tuple[str, str]] = [
    (r"^request system (reboot|halt|power-off|zeroize)", "Reboot/zeroize"),
    (r"^(reload|write erase|erase startup-config|format )", "Reload/erase"),
    (r"^clear bgp neighbor( all|\s*\*)?$|^clear ip bgp \*", "Hard BGP reset of all neighbours"),
    (r"^delete( |$)(?!interfaces \S+ description)", "Top-level delete"),
    (r"^load override", "Full config replace"),
    (r"^execute (factoryreset|reboot|formatlogdisk)", "FortiGate destructive execute"),
    (r"^/system reset-configuration", "RouterOS reset"),
]


@dataclass
class RiskReport:
    score: int
    level: str
    findings: list[str] = field(default_factory=list)
    summary: str = ""


def _level(score: int) -> str:
    return "critical" if score >= 70 else "high" if score >= 40 else "medium" if score >= 15 else "low"


def analyse_diff(unified_diff: str) -> RiskReport:
    score = 0
    findings: list[str] = []
    added = removed = 0
    touched: dict[str, int] = {}
    for line in unified_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        sign, body = line[:1], line[1:]
        if sign not in "+-" or not body.strip():
            continue
        if sign == "+":
            added += 1
        else:
            removed += 1
        m = re.match(r"^(?:set |delete )?(\S+)", body.strip())
        if m:
            touched[m.group(1)] = touched.get(m.group(1), 0) + 1
        for want_sign, pat, weight, why in DANGEROUS:
            if sign == want_sign and re.search(pat, body.strip()):
                score += weight
                findings.append(f"{why}: {body.strip()[:160]}")
                break
    # large changes are riskier by themselves
    volume = added + removed
    score += 5 if volume > 50 else 0
    score += 10 if volume > 500 else 0
    score = min(score, 100)
    areas = ", ".join(f"{k} ({v})" for k, v in sorted(touched.items(), key=lambda kv: -kv[1])[:5])
    summary = f"{added} line(s) added, {removed} removed" + (f"; most changes in {areas}" if areas else "")
    return RiskReport(score=score, level=_level(score), findings=findings[:50], summary=summary)


def classify_command(command: str) -> str | None:
    for pat, why in DANGEROUS_COMMANDS:
        if re.search(pat, command.strip()):
            return why
    return None
