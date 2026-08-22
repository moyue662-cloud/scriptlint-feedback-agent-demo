from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from repositories import SQLiteRepository
from schemas.scriptlint import (
    FindingType,
    ScriptAuditTask,
    ScriptFeedbackEvent,
    ScriptPlanStepStatus,
    ScriptRuleEffect,
    ScriptRuleStatus,
)
from scriptlint_phase2_demo import run_demo
from services.scriptlint_agent import ScriptLintAgent
from tools.scriptlint_tools import extract_script_facts, propose_script_rules


NOW = datetime(2026, 8, 22, 14, 0, tzinfo=timezone(timedelta(hours=8)))
FEEDBACK_TEXT = "这次判断不对。女主在第1到3集不能知道男主是集团继承人，这条规则只限制女主。"


@pytest.fixture()
def repo():
    value = SQLiteRepository(":memory:")
    value.init()
    yield value
    value.close()


def _task(*, project_id: str = "project_rainy_store") -> ScriptAuditTask:
    return ScriptAuditTask(
        id=f"task_{project_id}",
        team_id="team_scriptlint",
        project_id=project_id,
        episode=3,
        title="第3集身份揭示审计",
        script_text="场景：雨夜便利店。\n女主：原来你就是集团继承人。",
    )


def _feedback(*, project_id: str = "project_rainy_store") -> ScriptFeedbackEvent:
    return ScriptFeedbackEvent(
        id=f"feedback_{project_id}",
        team_id="team_scriptlint",
        project_id=project_id,
        original_result="系统未发现问题",
        user_text=FEEDBACK_TEXT,
        created_at=NOW,
    )


def test_raw_script_is_converted_to_evidence_fact():
    facts = extract_script_facts(_task())
    assert len(facts) == 2
    assert facts[0].subject == "女主"
    assert facts[0].action == "identity_reveal"
    assert facts[0].evidence_excerpt == "女主：原来你就是集团继承人。"
    assert facts[1].action == "speak_dialogue"


def test_natural_language_feedback_becomes_scoped_candidate():
    rules = propose_script_rules(_feedback())
    assert len(rules) == 1
    rule = rules[0]
    assert rule.status == ScriptRuleStatus.candidate
    assert rule.effect == ScriptRuleEffect.forbid
    assert (rule.episode_from, rule.episode_to) == (1, 3)
    assert rule.source_excerpt == FEEDBACK_TEXT


def test_underspecified_feedback_does_not_invent_rule():
    feedback = _feedback().model_copy(update={"user_text": "我不喜欢这个结果，再改改。"})
    assert propose_script_rules(feedback) == []


def test_candidate_is_persisted_but_not_retrieved_before_confirmation(repo):
    agent = ScriptLintAgent(repo)
    result = agent.receive_feedback(
        feedback_id="feedback_001",
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        original_result="系统未发现问题",
        user_text=FEEDBACK_TEXT,
        now=NOW,
    )
    assert repo.get_script_feedback("feedback_001") is not None
    assert len(result.candidates) == 1
    assert len(repo.list_script_rules(
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        status=ScriptRuleStatus.candidate,
    )) == 1
    assert repo.list_script_rules(
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        status=ScriptRuleStatus.active,
    ) == []
    assert result.plan[-1].status == ScriptPlanStepStatus.pending


def test_confirmation_changes_later_result_but_candidate_does_not(repo):
    agent = ScriptLintAgent(repo)
    task = _task()
    before = agent.analyze(task=task, run_id="run_before", now=NOW)
    feedback = agent.receive_feedback(
        feedback_id="feedback_001",
        team_id=task.team_id,
        project_id=task.project_id,
        original_result="系统未发现问题",
        user_text=FEEDBACK_TEXT,
        now=NOW,
    )
    candidate_only = agent.analyze(task=task, run_id="run_candidate", now=NOW)
    agent.confirm_rule(feedback.candidates[0].id)
    after = agent.analyze(task=task, run_id="run_after", now=NOW)

    assert before.audit.findings == []
    assert candidate_only.audit.findings == []
    assert [item.finding_type for item in after.audit.findings] == [FindingType.rule_violation]
    assert before.metrics.memory_applied_count == 0
    assert candidate_only.metrics.memory_applied_count == 0
    assert after.metrics.memory_applied_count == 1
    assert after.metrics.estimated_memory_tokens > 0
    assert after.retrieved_rules[0].source_feedback_id == "feedback_001"
    assert after.retrieved_rules[0].source_excerpt == FEEDBACK_TEXT
    assert after.task.facts[0].evidence_excerpt == "女主：原来你就是集团继承人。"


def test_agent_tool_trace_is_ordered_completed_and_persisted(repo):
    agent = ScriptLintAgent(repo)
    result = agent.analyze(task=_task(), run_id="run_trace", now=NOW)
    expected = [
        "retrieve_script_rules",
        "extract_script_facts",
        "audit_script_rules",
        "present_audit_result",
    ]
    assert [trace.tool_name for trace in result.tool_traces] == expected
    assert [trace.sequence for trace in result.tool_traces] == [1, 2, 3, 4]
    assert all(step.status == ScriptPlanStepStatus.completed for step in result.plan)
    assert [trace.tool_name for trace in repo.list_script_tool_traces("run_trace")] == expected
    assert result.metrics.model_call_count == 0


def test_active_rule_is_isolated_by_project(repo):
    agent = ScriptLintAgent(repo)
    feedback = agent.receive_feedback(
        feedback_id="feedback_001",
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        original_result="系统未发现问题",
        user_text=FEEDBACK_TEXT,
        now=NOW,
    )
    agent.confirm_rule(feedback.candidates[0].id)

    other = agent.analyze(
        task=_task(project_id="another_project"),
        run_id="run_other_project",
        now=NOW,
    )
    assert other.metrics.memory_hit_count == 0
    assert other.audit.findings == []


def test_rule_cannot_be_confirmed_twice(repo):
    agent = ScriptLintAgent(repo)
    feedback = agent.receive_feedback(
        feedback_id="feedback_001",
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        original_result="系统未发现问题",
        user_text=FEEDBACK_TEXT,
        now=NOW,
    )
    agent.confirm_rule(feedback.candidates[0].id)
    with pytest.raises(ValueError, match="只有 candidate 可以确认"):
        agent.confirm_rule(feedback.candidates[0].id)


def test_phase2_demo_proves_confirmation_gate():
    output = run_demo()
    assert output["data_label"] == "人工构造 · Demo"
    assert output["before_feedback"]["findings"] == []
    assert output["before_confirmation"]["findings"] == []
    assert output["confirmation"]["status"] == "active"
    assert output["after_confirmation"]["findings"] == ["rule_violation"]
