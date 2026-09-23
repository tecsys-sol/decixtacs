from __future__ import annotations

from typing import Any
from uuid import UUID

from networkops.models import ComplianceRule, ComplianceRun, parse
from networkops.resources._base import Resource


class Compliance(Resource):
    """Compliance rules, runs and golden configurations."""

    def rules(self) -> list[ComplianceRule]:
        return [parse(ComplianceRule, r) for r in self._c.get("/compliance/rules")]

    def create_rule(self, *, name: str, rule_type: str, pattern: str, severity: str = "medium",
                    **fields: Any) -> ComplianceRule:
        """rule_type: must_match | must_not_match | count_at_least | block_must_match."""
        return parse(ComplianceRule, self._c.post("/compliance/rules", json={
            "name": name, "rule_type": rule_type, "pattern": pattern, "severity": severity, **fields}))

    def update_rule(self, rule_id: UUID | str, **fields: Any) -> ComplianceRule:
        """PUT semantics: pass the full rule (name, rule_type, pattern, ...)."""
        return parse(ComplianceRule, self._c.put(f"/compliance/rules/{rule_id}", json=fields))

    def delete_rule(self, rule_id: UUID | str) -> None:
        self._c.delete(f"/compliance/rules/{rule_id}")

    def run(self) -> ComplianceRun:
        """Evaluate every rule against the latest backups now (synchronous)."""
        return parse(ComplianceRun, self._c.post("/compliance/run"))

    def runs(self, limit: int = 30) -> list[ComplianceRun]:
        return [parse(ComplianceRun, r) for r in self._c.get("/compliance/runs", params={"limit": limit})]

    def run_detail(self, run_id: UUID | str) -> dict[str, Any]:
        """``{"run", "devices": [...], "failures": [...], "failures_by_rule": {...}}``."""
        result: dict[str, Any] = self._c.get(f"/compliance/runs/{run_id}")
        return result

    def latest_score(self) -> float | None:
        runs = self.runs(limit=1)
        return runs[0].score if runs else None

    def golden_configs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._c.get("/golden-configs")
        return result

    def create_golden_config(self, *, name: str, content: str, device_id: UUID | str | None = None,
                             device_group_id: UUID | str | None = None, mode: str = "snippet",
                             ignore_patterns: list[str] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._c.post("/golden-configs", json={
            "name": name, "content": content, "device_id": device_id, "device_group_id": device_group_id,
            "mode": mode, "ignore_patterns": ignore_patterns or []})
        return result
