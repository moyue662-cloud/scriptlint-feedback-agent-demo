"""schemas/ 冻结验证测试（Part 2 退出条件）。

验证所有 Pydantic 模型可 import、可实例化、校验规则生效，
并能表达规格附录 C 的演示样例与 12.1 的演示数据。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from schemas import (
    AgentRun,
    ApplicabilityDecision,
    ApplicabilityJudgment,
    ChatLog,
    CreatedBy,
    DataSourceLabel,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
    FeedbackEvent,
    MemoryCandidate,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    Message,
    ParseWarning,
    RuleType,
    RunMode,
)

CST = timezone(timedelta(hours=8))


# ---------- message.py ----------

def test_message_minimal():
    m = Message(id="msg_001", project_id="p1", sender="A", content="要不 PPT 做成蓝色？")
    assert m.sent_at is None
    assert m.source_hash is None


def test_chatlog_with_warnings_and_source_label():
    log = ChatLog(
        project_id="p1",
        messages=[Message(id="msg_001", project_id="p1", sender="A", content="x")],
        warnings=[ParseWarning(line="???", reason="无法识别说话人")],
        source_label=DataSourceLabel.synthetic,
    )
    assert len(log.warnings) == 1
    assert log.source_label == DataSourceLabel.synthetic


# ---------- decision.py ----------

def test_decision_record_with_evidence():
    d = DecisionRecord(
        id="dec_001",
        team_id="team_demo",
        project_id="course_design",
        type=DecisionType.confirmed,
        summary="PPT 使用学校官方模板",
        owner="小李",
        evidence_message_ids=["msg_018", "msg_021"],
        confidence=0.91,
    )
    assert d.status == DecisionStatus.open
    assert d.created_by == CreatedBy.agent


def test_decision_no_evidence_must_be_conflict_or_unknown():
    # conflict 无证据 -> 允许
    DecisionRecord(
        id="dec_x",
        team_id="t",
        project_id="p",
        type=DecisionType.conflict,
        summary="待确认",
    )
    # unknown 无证据 -> 允许
    DecisionRecord(
        id="dec_y",
        team_id="t",
        project_id="p",
        type=DecisionType.unknown,
        summary="证据不足",
    )
    # confirmed 无证据 -> 应被拒绝
    with pytest.raises(ValidationError):
        DecisionRecord(
            id="dec_z",
            team_id="t",
            project_id="p",
            type=DecisionType.confirmed,
            summary="无证据的确认",
        )


def test_decision_confidence_out_of_range():
    with pytest.raises(ValidationError):
        DecisionRecord(
            id="dec_c",
            team_id="t",
            project_id="p",
            type=DecisionType.proposal,
            summary="x",
            evidence_message_ids=["m1"],
            confidence=1.5,
        )


# ---------- memory.py ----------

def test_memory_rule_candidate_default():
    r = MemoryRule(
        id="mem_007",
        team_id="team_demo",
        rule_type=RuleType.speech_act,
        trigger="句子包含'要不''可以试试''或许'",
        instruction="默认标记为 proposal，不得直接标记为 confirmed",
        source_feedback_id="fb_003",
        source_excerpt="这只是建议，还没定",
        confidence=0.92,
        created_at=datetime(2026, 8, 20, 16, 0, tzinfo=CST),
    )
    assert r.status == MemoryStatus.candidate
    assert r.scope == MemoryScope.team
    assert r.project_id is None


def test_memory_project_scope_requires_project_id():
    with pytest.raises(ValidationError):
        MemoryRule(
            id="mem_bad",
            team_id="t",
            rule_type=RuleType.hard_constraint,
            trigger="x",
            instruction="y",
            scope=MemoryScope.project,
            created_at=datetime(2026, 8, 20, tzinfo=CST),
        )


def test_applicability_judgment():
    j = ApplicabilityJudgment(
        memory_id="mem_007",
        decision=ApplicabilityDecision.apply,
        reason="本轮消息包含'要不'，且尚无队长确认",
        evidence_message_ids=["msg_044"],
    )
    assert j.decision == ApplicabilityDecision.apply


# ---------- feedback.py ----------

def test_feedback_event_and_candidate():
    fb = FeedbackEvent(
        id="fb_003",
        team_id="team_demo",
        project_id="course_design",
        decision_id="dec_001",
        before_json='{"type":"confirmed"}',
        after_json='{"type":"proposal"}',
        user_text="这只是建议，还没定",
        created_at=datetime(2026, 8, 20, 17, 0, tzinfo=CST),
    )
    assert fb.user_text == "这只是建议，还没定"

    c = MemoryCandidate(
        id="cand_001",
        feedback_id="fb_003",
        team_id="team_demo",
        rule_type=RuleType.speech_act,
        trigger="句子包含'要不'",
        instruction="默认标记为 proposal",
        source_excerpt="这只是建议，还没定",
        confidence=0.9,
    )
    assert c.scope == MemoryScope.team


# ---------- metrics.py ----------

def test_agent_run_defaults_and_mode():
    run = AgentRun(
        id="run_001",
        team_id="team_demo",
        project_id="course_design",
        latency_ms=420,
        memory_tokens=180,
        memory_hit_count=3,
        memory_applied_count=2,
        created_at=datetime(2026, 8, 20, 18, 0, tzinfo=CST),
    )
    assert run.mode == RunMode.decisionpatch
    assert run.memory_tokens <= 300  # 规格目标


# ---------- 附录 C 演示样例可表达性 ----------

def test_appendix_c_samples_representable():
    samples = [
        ("要不我们用蓝色主题？", DecisionType.proposal),
        ("按老师发的模板做，所有人统一。", DecisionType.confirmed),
        ("蓝色方案不用了，和学院模板冲突。", DecisionType.rejected),
        ("小李今晚九点前合并前端。", DecisionType.task),
        ("先这样吧，明天再确认。", DecisionType.conflict),
    ]
    for i, (summary, dtype) in enumerate(samples):
        d = DecisionRecord(
            id=f"dec_c{i}",
            team_id="team_demo",
            project_id="course_design",
            type=dtype,
            summary=summary,
            evidence_message_ids=[f"msg_c{i}"],
        )
        assert d.type == dtype
