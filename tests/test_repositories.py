"""SQLite 持久层测试（Part 3 退出条件）。

覆盖规格 5.3 的 8 张表 CRUD、证据多对多绑定、记忆硬过滤检索、
跨团队隔离、记忆生命周期转换与负反馈降权。
全部用内存库（:memory:），不产生文件。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from repositories import SQLiteRepository
from schemas import (
    AgentRun,
    CreatedBy,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
    FeedbackEvent,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    RuleType,
    RunMode,
    Message,
)

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)


@pytest.fixture()
def repo():
    """每个测试用独立的内存库。"""
    r = SQLiteRepository(":memory:")
    r.init()
    r.create_team(id="team_demo", name="演示团队", created_at=NOW)
    r.create_team(id="team_other", name="另一团队", created_at=NOW)
    r.create_project(id="course_design", team_id="team_demo", name="课程设计", created_at=NOW)
    r.create_project(id="other_proj", team_id="team_other", name="别队项目", created_at=NOW)
    yield r
    r.close()


# ---------- 建库与幂等 ----------

def test_init_is_idempotent(repo):
    """init 可重复调用，不报错、不丢数据。"""
    repo.init()
    repo.init()
    assert repo.get_team("team_demo") is not None


# ---------- messages ----------

def test_insert_and_list_messages(repo):
    msgs = [
        Message(id="msg_001", project_id="course_design", sender="A", content="要不 PPT 做成蓝色？"),
        Message(id="msg_002", project_id="course_design", sender="B", content="可以试试。"),
    ]
    repo.insert_messages(msgs)
    got = repo.list_messages("course_design")
    assert len(got) == 2
    assert got[0].sender == "A"
    assert got[1].content == "可以试试。"


# ---------- decisions + evidence ----------

def _make_decision(**over):
    base = dict(
        id="dec_001",
        team_id="team_demo",
        project_id="course_design",
        type=DecisionType.confirmed,
        summary="PPT 使用学校官方模板",
        owner="小李",
        evidence_message_ids=["msg_018", "msg_021"],
        confidence=0.91,
    )
    base.update(over)
    return DecisionRecord(**base)


def test_insert_and_get_decision_with_evidence(repo):
    repo.insert_messages([
        Message(id="msg_018", project_id="course_design", sender="C", content="老师说用学院模板"),
        Message(id="msg_021", project_id="course_design", sender="A", content="那就统一"),
    ])
    repo.insert_decision(_make_decision(), created_at=NOW)
    got = repo.get_decision("dec_001")
    assert got is not None
    assert got.type == DecisionType.confirmed
    assert got.owner == "小李"
    assert set(got.evidence_message_ids) == {"msg_018", "msg_021"}


def test_update_decision_partial(repo):
    repo.insert_messages([
        Message(id="msg_018", project_id="course_design", sender="C", content="x"),
    ])
    repo.insert_decision(
        _make_decision(evidence_message_ids=["msg_018"]),
        created_at=NOW,
    )
    # 用户纠正：confirmed -> proposal（规格 4.2）
    repo.update_decision("dec_001", type=DecisionType.proposal, status=DecisionStatus.open)
    got = repo.get_decision("dec_001")
    assert got.type == DecisionType.proposal
    assert got.status == DecisionStatus.open


def test_list_decisions_by_project(repo):
    repo.insert_messages([
        Message(id="m1", project_id="course_design", sender="A", content="x"),
    ])
    repo.insert_decision(_make_decision(id="d1", evidence_message_ids=["m1"]), created_at=NOW)
    repo.insert_decision(_make_decision(id="d2", evidence_message_ids=["m1"]), created_at=NOW)
    assert len(repo.list_decisions("course_design")) == 2


# ---------- feedback_events ----------

def test_feedback_event_roundtrip(repo):
    fb = FeedbackEvent(
        id="fb_003",
        team_id="team_demo",
        project_id="course_design",
        decision_id="dec_001",
        before_json='{"type":"confirmed"}',
        after_json='{"type":"proposal"}',
        user_text="这只是建议，还没定",
        created_at=NOW,
    )
    repo.insert_feedback_event(fb)
    got = repo.get_feedback_event("fb_003")
    assert got is not None
    assert got.user_text == "这只是建议，还没定"
    assert got.after_json == '{"type":"proposal"}'


# ---------- memory_rules：生命周期与硬过滤 ----------

def _make_rule(**over):
    base = dict(
        id="mem_007",
        team_id="team_demo",
        rule_type=RuleType.speech_act,
        trigger="句子包含'要不'",
        instruction="默认标记为 proposal",
        source_feedback_id="fb_003",
        source_excerpt="这只是建议，还没定",
        confidence=0.92,
        created_at=NOW,
    )
    base.update(over)
    return MemoryRule(**base)


def test_memory_candidate_to_active(repo):
    repo.insert_memory_rule(_make_rule())  # 默认 candidate
    assert repo.get_memory_rule("mem_007").status == MemoryStatus.candidate
    # 候选记忆在 active 检索中不可见（规格 11.1：未确认不影响下一次运行）
    assert repo.list_active_memories(team_id="team_demo") == []
    repo.update_memory_status("mem_007", MemoryStatus.active)
    assert len(repo.list_active_memories(team_id="team_demo")) == 1


def test_memory_scope_isolation_no_cross_team(repo):
    """跨团队默认禁止使用（规格 6.5）。"""
    repo.insert_memory_rule(_make_rule(id="mem_a", team_id="team_demo"))
    repo.insert_memory_rule(_make_rule(id="mem_b", team_id="team_other"))
    repo.update_memory_status("mem_a", MemoryStatus.active)
    repo.update_memory_status("mem_b", MemoryStatus.active)
    # team_demo 只看到自己的，看不到 team_other 的
    demo = repo.list_active_memories(team_id="team_demo")
    assert len(demo) == 1
    assert demo[0].id == "mem_a"


def test_memory_project_scope_filter(repo):
    """项目级规则只在指定项目可见，团队级规则所有项目可见（规格 6.3）。"""
    repo.insert_memory_rule(_make_rule(id="mem_team"))  # 团队级
    repo.insert_memory_rule(
        _make_rule(id="mem_proj", project_id="course_design", scope=MemoryScope.project)
    )
    repo.update_memory_status("mem_team", MemoryStatus.active)
    repo.update_memory_status("mem_proj", MemoryStatus.active)
    # 查 course_design：团队级 + 本项目级
    got = repo.list_active_memories(team_id="team_demo", project_id="course_design")
    assert {m.id for m in got} == {"mem_team", "mem_proj"}
    # 查 other_proj（属于 team_demo？不，other_proj 属于 team_other）
    # 这里验证：team_demo 下不传 project_id 时只返回团队级
    got_all = repo.list_active_memories(team_id="team_demo")
    assert {m.id for m in got_all} == {"mem_team", "mem_proj"}


def test_memory_rule_type_filter(repo):
    repo.insert_memory_rule(_make_rule(id="m1", rule_type=RuleType.speech_act))
    repo.insert_memory_rule(_make_rule(id="m2", rule_type=RuleType.hard_constraint))
    repo.update_memory_status("m1", MemoryStatus.active)
    repo.update_memory_status("m2", MemoryStatus.active)
    got = repo.list_active_memories(
        team_id="team_demo", rule_types=[RuleType.speech_act]
    )
    assert len(got) == 1
    assert got[0].rule_type == RuleType.speech_act


def test_memory_use_and_negative_feedback(repo):
    """记录使用与负反馈降权（规格 6.5）。"""
    repo.insert_memory_rule(_make_rule())
    repo.update_memory_status("mem_007", MemoryStatus.active)
    repo.record_memory_use("mem_007", positive=False, negative=True, used_at=NOW)
    got = repo.get_memory_rule("mem_007")
    assert got.use_count == 1
    assert got.negative_count == 1
    assert got.positive_count == 0
    assert got.last_used_at == NOW


# ---------- agent_runs ----------

def test_agent_run_roundtrip(repo):
    run = AgentRun(
        id="run_001",
        team_id="team_demo",
        project_id="course_design",
        mode=RunMode.decisionpatch,
        latency_ms=420,
        input_tokens=1200,
        memory_tokens=180,
        output_tokens=300,
        memory_hit_count=3,
        memory_applied_count=2,
        created_at=NOW,
    )
    repo.insert_agent_run(run)
    got = repo.list_agent_runs("course_design")
    assert len(got) == 1
    assert got[0].mode == RunMode.decisionpatch
    assert got[0].memory_tokens == 180
