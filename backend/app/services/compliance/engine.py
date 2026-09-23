"""Module 6 - configuration compliance policy engine.

Rule types
----------
``must_match``        at least one line matches ``pattern`` (e.g. ``^set system ntp server``)
``must_not_match``    no line matches ``pattern`` (e.g. ``snmp.*community "?public``)
``count_at_least``    at least ``min_count`` lines match (e.g. 2 NTP servers)
``block_must_match``  every block opened by ``block_start`` (e.g. ``^interface Eth``) contains ``pattern``

Scores are weighted by severity so one critical failure hurts more than three low ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEVERITY_WEIGHT = {"low": 1, "medium": 3, "high": 6, "critical": 10}


@dataclass
class Rule:
    id: str
    name: str
    rule_type: str
    pattern: str
    severity: str = "medium"
    block_start: str | None = None
    min_count: int = 1
    platforms: tuple[str, ...] = ()


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    detail: str


def _blocks(lines: list[str], start: re.Pattern) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for ln in lines:
        if start.search(ln):
            current = (ln.strip(), [])
            blocks.append(current)
        elif current is not None:
            if ln[:1] in (" ", "\t"):
                current[1].append(ln)
            else:
                current = None
    return blocks


def evaluate_rule(rule: Rule, config: str) -> RuleResult:
    try:
        rx = re.compile(rule.pattern, re.MULTILINE | re.IGNORECASE)
    except re.error as exc:
        return RuleResult(rule.id, False, f"invalid pattern: {exc}")
    lines = config.splitlines()
    if rule.rule_type == "must_match":
        hit = next((ln for ln in lines if rx.search(ln)), None)
        return RuleResult(rule.id, hit is not None, f"matched: {hit.strip()}" if hit else "required line not found")
    if rule.rule_type == "must_not_match":
        hits = [ln.strip() for ln in lines if rx.search(ln)]
        return RuleResult(rule.id, not hits, "no forbidden lines" if not hits else "forbidden: " + "; ".join(hits[:5]))
    if rule.rule_type == "count_at_least":
        n = sum(1 for ln in lines if rx.search(ln))
        return RuleResult(rule.id, n >= rule.min_count, f"{n} matching line(s), need {rule.min_count}")
    if rule.rule_type == "block_must_match":
        if not rule.block_start:
            return RuleResult(rule.id, False, "block_start missing")
        failing = [
            hdr for hdr, body in _blocks(lines, re.compile(rule.block_start)) if not any(rx.search(b) for b in body)
        ]
        return RuleResult(
            rule.id, not failing, "all blocks compliant" if not failing else "non-compliant: " + "; ".join(failing[:10])
        )
    return RuleResult(rule.id, False, f"unknown rule type {rule.rule_type}")


def evaluate(rules: list[Rule], config: str, platform: str | None) -> tuple[list[RuleResult], float]:
    applicable = [r for r in rules if not r.platforms or platform in r.platforms]
    results = [evaluate_rule(r, config) for r in applicable]
    return results, score(applicable, results)


def score(rules: list[Rule], results: list[RuleResult]) -> float:
    by_id = {r.id: r for r in rules}
    total = sum(SEVERITY_WEIGHT.get(by_id[x.rule_id].severity, 3) for x in results)
    if not total:
        return 100.0
    ok = sum(SEVERITY_WEIGHT.get(by_id[x.rule_id].severity, 3) for x in results if x.passed)
    return round(100.0 * ok / total, 2)


# Starter policy pack for ISP/IXP networks (seeded per tenant).
DEFAULT_RULES: list[dict] = [
    {
        "name": "SNMP community must not be public",
        "rule_type": "must_not_match",
        "pattern": r"community\s+\"?(public|private)\b",
        "severity": "critical",
    },
    {
        "name": "At least two NTP servers",
        "rule_type": "count_at_least",
        "min_count": 2,
        "pattern": r"^(set system ntp server|ntp server|set system ntp server-address)",
        "severity": "medium",
    },
    {
        "name": "Syslog server configured",
        "rule_type": "must_match",
        "pattern": r"^(set system syslog host|logging host|logging \d+\.|set log syslog)",
        "severity": "high",
    },
    {
        "name": "SSH v2 only (IOS)",
        "rule_type": "must_match",
        "pattern": r"^ip ssh version 2",
        "severity": "high",
        "platforms": ["ios"],
    },
    {
        "name": "Telnet disabled (Junos)",
        "rule_type": "must_not_match",
        "pattern": r"^set system services telnet",
        "severity": "critical",
        "platforms": ["junos"],
    },
    {
        "name": "TACACS+ authentication configured (Junos)",
        "rule_type": "must_match",
        "pattern": r"^set system tacplus-server",
        "severity": "high",
        "platforms": ["junos"],
    },
    {
        "name": "TACACS+ authentication configured (EOS/IOS)",
        "rule_type": "must_match",
        "pattern": r"^(tacacs-server host|tacacs server)",
        "severity": "high",
        "platforms": ["eos", "ios", "nxos"],
    },
    {
        "name": "Command accounting enabled (EOS/IOS)",
        "rule_type": "must_match",
        "pattern": r"^aaa accounting commands",
        "severity": "high",
        "platforms": ["eos", "ios", "nxos"],
    },
    {
        "name": "RE protection filter applied (Junos)",
        "rule_type": "must_match",
        "pattern": r"^set interfaces lo0 unit 0 family inet filter input",
        "severity": "high",
        "platforms": ["junos"],
    },
    {
        "name": "BGP neighbours have descriptions (IOS/EOS)",
        "rule_type": "block_must_match",
        "block_start": r"^router bgp",
        "pattern": r"neighbor \S+ description",
        "severity": "low",
        "platforms": ["ios", "eos"],
    },
]
