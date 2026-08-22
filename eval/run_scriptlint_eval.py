"""ScriptLint 人工构造评测：无记忆与确认记忆双组对照。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field, model_validator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories import SQLiteRepository
from schemas.scriptlint import (
    FindingType,
    RuleUseDecision,
    ScriptAuditTask,
    ScriptRule,
)
from services.scriptlint_agent import ScriptLintAgent


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "scriptlint_eval.json"


class ScriptLintEvalCase(BaseModel):
    id: str
    category: str
    task: ScriptAuditTask
    rule_ids: list[str] = Field(default_factory=list)
    expected_applied: list[str] = Field(default_factory=list)
    expected_ignored: list[str] = Field(default_factory=list)
    expected_conflicted: list[str] = Field(default_factory=list)
    expected_findings: list[FindingType] = Field(default_factory=list)


class ScriptLintEvalFixture(BaseModel):
    schema_version: str
    data_label: str
    rules: list[ScriptRule]
    cases: list[ScriptLintEvalCase]

    @model_validator(mode="after")
    def _references_exist(self) -> "ScriptLintEvalFixture":
        rule_ids = {rule.id for rule in self.rules}
        for case in self.cases:
            missing = set(case.rule_ids) - rule_ids
            if missing:
                raise ValueError(f"评测案例引用不存在的规则: {sorted(missing)}")
        return self


def load_scriptlint_eval() -> ScriptLintEvalFixture:
    return ScriptLintEvalFixture.model_validate_json(
        FIXTURE_PATH.read_text(encoding="utf-8")
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def run_scriptlint_eval() -> dict:
    fixture = load_scriptlint_eval()
    rule_map = {rule.id: rule for rule in fixture.rules}
    mode_results: dict[str, list[dict]] = {"no_memory": [], "confirmed_memory": []}

    for mode in mode_results:
        for case_index, case in enumerate(fixture.cases, start=1):
            repo = SQLiteRepository(":memory:")
            repo.init()
            if mode == "confirmed_memory":
                for rule_id in case.rule_ids:
                    repo.insert_script_rule(rule_map[rule_id])
            agent = ScriptLintAgent(repo)
            result = agent.analyze(
                task=case.task,
                run_id=f"eval_{mode}_{case_index:02d}",
                now=fixture.rules[0].created_at,
            )
            applied = [
                trace.rule_id for trace in result.audit.traces
                if trace.decision == RuleUseDecision.apply
            ]
            ignored = [
                trace.rule_id for trace in result.audit.traces
                if trace.decision == RuleUseDecision.ignore
            ]
            conflicted = [
                trace.rule_id for trace in result.audit.traces
                if trace.decision == RuleUseDecision.conflict
            ]
            findings = [finding.finding_type.value for finding in result.audit.findings]
            expected_findings = [finding.value for finding in case.expected_findings]
            decision_match = (
                applied == case.expected_applied
                and ignored == case.expected_ignored
                and conflicted == case.expected_conflicted
            )
            finding_match = findings == expected_findings
            source_traceable = all(
                rule.source_feedback_id and rule.source_excerpt
                for rule in result.retrieved_rules
            )
            mode_results[mode].append(
                {
                    "id": case.id,
                    "category": case.category,
                    "decision_match": decision_match,
                    "finding_match": finding_match,
                    "passed": finding_match and (decision_match if mode == "confirmed_memory" else True),
                    "applied": applied,
                    "ignored": ignored,
                    "conflicted": conflicted,
                    "findings": findings,
                    "expected_findings": expected_findings,
                    "latency_ms": result.metrics.latency_ms,
                    "estimated_memory_tokens": result.metrics.estimated_memory_tokens,
                    "model_calls": result.metrics.model_call_count,
                    "source_traceable": bool(result.retrieved_rules) and bool(source_traceable),
                }
            )
            repo.close()

    reports: list[dict] = []
    for mode, rows in mode_results.items():
        latencies = [row["latency_ms"] for row in rows]
        reports.append(
            {
                "mode": mode,
                "case_count": len(rows),
                "finding_exact_match_rate": mean(row["finding_match"] for row in rows),
                "decision_exact_match_rate": (
                    mean(row["decision_match"] for row in rows)
                    if mode == "confirmed_memory" else None
                ),
                "p95_latency_ms": _percentile(latencies, 95),
                "avg_estimated_memory_tokens": mean(
                    row["estimated_memory_tokens"] for row in rows
                ),
                "model_call_count": sum(row["model_calls"] for row in rows),
                "details": rows,
            }
        )

    baseline_errors = sum(not row["finding_match"] for row in mode_results["no_memory"])
    memory_errors = sum(not row["finding_match"] for row in mode_results["confirmed_memory"])
    error_reduction = (
        (baseline_errors - memory_errors) / baseline_errors if baseline_errors else 0.0
    )
    guard_categories = {"confirmation_gate", "project_isolation"}
    guard_rows = [
        row for row in mode_results["confirmed_memory"]
        if row["category"] in guard_categories
    ]
    return {
        "schema_version": fixture.schema_version,
        "data_label": fixture.data_label,
        "case_count": len(fixture.cases),
        "reports": reports,
        "same_type_error_reduction": error_reduction,
        "guard_pass_rate": mean(row["passed"] for row in guard_rows),
        "cross_project_leakage": sum(
            bool(row["applied"])
            for row in mode_results["confirmed_memory"]
            if row["category"] == "project_isolation"
        ),
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run_scriptlint_eval(), ensure_ascii=False, indent=2))
