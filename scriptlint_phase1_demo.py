"""运行 ScriptLint 第一阶段人工构造 Demo。

用法：py -B scriptlint_phase1_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from schemas.scriptlint import RuleUseDecision, ScriptLintDemoFixture
from services.scriptlint_audit_service import ScriptLintAuditService


FIXTURE_PATH = Path(__file__).parent / "eval" / "fixtures" / "scriptlint_demo.json"


def load_fixture() -> ScriptLintDemoFixture:
    return ScriptLintDemoFixture.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def run_demo() -> list[dict]:
    fixture = load_fixture()
    rule_map = {rule.id: rule for rule in fixture.confirmed_rules}
    service = ScriptLintAuditService()
    summaries: list[dict] = []

    for case in fixture.cases:
        rules = [rule_map[rule_id] for rule_id in case.rule_ids]
        result = service.audit(task=case.task, rules=rules)
        summaries.append(
            {
                "case": case.id,
                "description": case.description,
                "applied": [
                    trace.rule_id
                    for trace in result.traces
                    if trace.decision == RuleUseDecision.apply
                ],
                "ignored": [
                    trace.rule_id
                    for trace in result.traces
                    if trace.decision == RuleUseDecision.ignore
                ],
                "conflicted": [
                    trace.rule_id
                    for trace in result.traces
                    if trace.decision == RuleUseDecision.conflict
                ],
                "findings": [finding.finding_type.value for finding in result.findings],
                "metrics": result.metrics.model_dump(),
            }
        )
    return summaries


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
