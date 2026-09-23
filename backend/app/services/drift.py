"""Configuration drift detection: running vs last backup vs golden config."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services import diff as diffsvc


@dataclass
class DriftResult:
    drifted: bool
    diff: str
    missing_lines: list[str]


def _filter(text: str, ignore: list[str]) -> str:
    if not ignore:
        return text
    rx = [re.compile(p) for p in ignore]
    return "\n".join(ln for ln in text.splitlines() if not any(r.search(ln) for r in rx))


def compare_running(running: str, backup: str, ignore: list[str] | None = None) -> DriftResult:
    a, b = _filter(backup, ignore or []), _filter(running, ignore or [])
    d = diffsvc.unified(a, b, "last-backup", "running")
    return DriftResult(bool(d), d, [])


def compare_golden(config: str, golden: str, mode: str, ignore: list[str] | None = None) -> DriftResult:
    config_f = _filter(config, ignore or [])
    golden_f = _filter(golden, ignore or [])
    if mode == "full":
        d = diffsvc.unified(golden_f, config_f, "golden", "actual")
        return DriftResult(bool(d), d, [])
    present = {ln.strip() for ln in config_f.splitlines()}
    missing = [ln.strip() for ln in golden_f.splitlines() if ln.strip() and not ln.strip().startswith(("#", "!"))
               and ln.strip() not in present]
    d = "\n".join(f"- {m}" for m in missing)
    return DriftResult(bool(missing), d, missing)
