from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scriptlint_phase1_demo import load_fixture, run_demo
from schemas.scriptlint import (
    FindingType,
    RuleUseDecision,
    ScriptRule,
    ScriptRuleEffect,
    ScriptRuleStatus,
)
from services.scriptlint_audit_service import ScriptLintAuditService


FIXTURE_PATH = Path(__file__).parents[1] / "eval" / "fixtures" / "scriptlint_demo.json"


def test_phase1_fixture_is_explicitly_synthetic_and_valid():
    fixture = load_fixture()
    assert FIXTURE_PATH.exists()
    assert fixture.data_label == "人工构造 · Demo"
    assert fixture.project_name.endswith("（人工构造）")


def test_candidate_rule_requires_feedback_source():
    with pytest.raises(ValidationError):
        ScriptRule(
            id="rule_bad",
            team_id="team",
            project_id="project",
            rule_type="timeline",
            title="bad",
            subject="女主",
            action="identity_reveal",
            effect="forbid",
            requirement="不得揭示",
            status="candidate",
        )


def test_rule_episode_range_must_be_valid():
    with pytest.raises(ValidationError):
        ScriptRule(
            id="rule_bad_range",
            team_id="team",
            project_id="project",
            rule_type="timeline",
            title="bad range",
            subject="女主",
            action="identity_reveal",
            effect="forbid",
            requirement="不得揭示",
            episode_from=4,
            episode_to=3,
            source_feedback_id="fb",
            source_excerpt="source",
        )


def test_no_memory_and_confirmed_memory_produce_measurable_delta():
    results = {item["case"]: item for item in run_demo()}
    baseline = results["case_no_memory"]
    after = results["case_memory_applies"]

    assert baseline["findings"] == []
    assert baseline["metrics"]["memory_applied_count"] == 0
    assert after["applied"] == ["rule_017"]
    assert after["findings"] == [FindingType.rule_violation.value]
    assert after["metrics"]["memory_applied_count"] == 1


def test_memory_is_ignored_outside_episode_scope():
    fixture = load_fixture()
    case = next(c for c in fixture.cases if c.id == "case_memory_ignored_out_of_scope")
    rule = next(r for r in fixture.confirmed_rules if r.id == "rule_017")

    result = ScriptLintAuditService().audit(task=case.task, rules=[rule])

    assert result.findings == []
    assert result.traces[0].decision == RuleUseDecision.ignore
    assert "第4集" in result.traces[0].reason


def test_cross_project_memory_is_neither_used_nor_counted_as_hit():
    fixture = load_fixture()
    case = next(c for c in fixture.cases if c.id == "case_memory_applies")
    rule = next(r for r in fixture.confirmed_rules if r.id == "rule_017")
    foreign_rule = rule.model_copy(update={"id": "foreign_rule", "project_id": "other"})

    result = ScriptLintAuditService().audit(task=case.task, rules=[foreign_rule])

    assert result.traces == []
    assert result.findings == []
    assert result.metrics.memory_hit_count == 0


def test_conflicting_confirmed_rules_stop_automatic_application():
    fixture = load_fixture()
    case = next(c for c in fixture.cases if c.id == "case_rule_conflict")
    rule_map = {rule.id: rule for rule in fixture.confirmed_rules}

    result = ScriptLintAuditService().audit(
        task=case.task,
        rules=[rule_map[rule_id] for rule_id in case.rule_ids],
    )

    assert [f.finding_type for f in result.findings] == [FindingType.rule_conflict]
    assert all(trace.decision == RuleUseDecision.conflict for trace in result.traces)
    assert result.metrics.memory_conflict_count == 2


def test_fixture_expectations_match_deterministic_service():
    fixture = load_fixture()
    results = {item["case"]: item for item in run_demo()}
    for case in fixture.cases:
        actual = results[case.id]
        assert actual["applied"] == case.expected_applied_rule_ids
        assert actual["ignored"] == case.expected_ignored_rule_ids
        assert actual["findings"] == [kind.value for kind in case.expected_finding_types]


def test_confirmed_demo_rule_has_expected_semantics():
    fixture = load_fixture()
    rule = next(r for r in fixture.confirmed_rules if r.id == "rule_017")
    assert rule.status == ScriptRuleStatus.active
    assert rule.effect == ScriptRuleEffect.forbid
    assert rule.episode_from == 1
    assert rule.episode_to == 3
