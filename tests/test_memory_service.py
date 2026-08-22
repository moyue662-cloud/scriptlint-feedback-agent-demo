"""memory_service 单元测试（Part 6 第一个文件）。

覆盖规格 §6.3（检索/注入）、§6.4（优先级）、§6.5（作用域隔离/反馈降权）。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from config import AppConfig
from repositories.sqlite import SQLiteRepository
from schemas import (
    ApplicabilityDecision,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    RuleType,
)
from services.memory_service import MemoryService

CST = timezone(timedelta(hours=8))
_NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)


def _make_repo() -> SQLiteRepository:
    repo = SQLiteRepository(":memory:")
    repo.init()
    repo.create_team(id="team_a", name="A 组", created_at=_NOW)
    repo.create_team(id="team_b", name="B 组", created_at=_NOW)
    repo.create_project(id="proj_a", team_id="team_a", name="A 项目", created_at=_NOW)
    return repo


def _active_rule(
    *,
    id: str,
    team_id: str = "team_a",
    project_id: str | None = None,
    rule_type: RuleType = RuleType.speech_act,
    trigger: str = "句子包含'要不'",
    instruction: str = "默认标记为 proposal",
    confidence: float = 0.9,
    scope: MemoryScope = MemoryScope.team,
) -> MemoryRule:
    return MemoryRule(
        id=id,
        team_id=team_id,
        project_id=project_id,
        rule_type=rule_type,
        trigger=trigger,
        instruction=instruction,
        scope=scope,
        confidence=confidence,
        status=MemoryStatus.active,
        created_at=_NOW,
    )


# ---------- 作用域隔离（规格 §6.5）----------

def test_retrieve_isolates_by_team():
    """跨团队默认禁止使用：team_b 的记忆不会在 team_a 检索中出现。"""
    repo = _make_repo()
    repo.insert_memory_rule(_active_rule(id="mem_b", team_id="team_b"))
    svc = MemoryService(repo)

    got = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert got == []  # 不泄漏


def test_retrieve_returns_own_team_rules():
    repo = _make_repo()
    repo.insert_memory_rule(_active_rule(id="mem_a", team_id="team_a"))
    svc = MemoryService(repo)

    got = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert [m.id for m in got] == ["mem_a"]


# ---------- 召回 top-k（规格 §6.3 第 2 步）----------

def test_retrieve_respects_topk():
    repo = _make_repo()
    # 插入 10 条都命中的记忆
    for i in range(10):
        repo.insert_memory_rule(_active_rule(id=f"mem_{i}", confidence=0.5))
    cfg = AppConfig(memory_recall_topk=3)
    svc = MemoryService(repo, config=cfg)

    got = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert len(got) == 3  # top-k 截断


# ---------- 适用性判断（规格 §6.3 第 3 步 / §9.3）----------

def test_judge_applicability_apply_on_keyword_hit():
    repo = _make_repo()
    svc = MemoryService(repo)
    rules = [_active_rule(id="mem_hit", trigger="句子包含'要不'")]

    judgments = svc.judge_applicability(memories=rules, query="要不我们用蓝色主题")
    assert judgments[0].decision == ApplicabilityDecision.apply


def test_judge_applicability_ignore_on_no_hit():
    repo = _make_repo()
    svc = MemoryService(repo)
    rules = [_active_rule(id="mem_miss", trigger="句子包含要不")]

    judgments = svc.judge_applicability(memories=rules, query="今天天气不错")
    assert judgments[0].decision == ApplicabilityDecision.ignore


# ---------- 注入预算（规格 §6.3 第 4-5 步）----------

def test_build_injection_only_applies_marked():
    """只注入 decision=apply 的记忆。"""
    repo = _make_repo()
    svc = MemoryService(repo)
    rules = [
        _active_rule(id="mem_apply", trigger="要不"),
        _active_rule(id="mem_ignore", trigger="完全无关的词"),
    ]
    # 手动构造判断：第一条 apply，第二条 ignore
    from schemas import ApplicabilityJudgment

    judgments = [
        ApplicabilityJudgment(
            memory_id="mem_apply",
            decision=ApplicabilityDecision.apply,
            reason="命中",
        ),
        ApplicabilityJudgment(
            memory_id="mem_ignore",
            decision=ApplicabilityDecision.ignore,
            reason="未命中",
        ),
    ]
    injected = svc.build_injection(memories=rules, judgments=judgments)
    assert [m.id for m in injected] == ["mem_apply"]


def test_build_injection_respects_max_rules():
    repo = _make_repo()
    for i in range(5):
        repo.insert_memory_rule(_active_rule(id=f"mem_{i}", confidence=0.5))
    cfg = AppConfig(memory_max_rules=2)
    svc = MemoryService(repo, config=cfg)

    rules = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    judgments = svc.judge_applicability(memories=rules, query="要不")
    injected = svc.build_injection(memories=rules, judgments=judgments)
    assert len(injected) <= 2


def test_build_injection_respects_token_budget():
    """单条记忆 token 超预算时被跳过，不强行截断。"""
    repo = _make_repo()
    long_rule = _active_rule(
        id="mem_long",
        trigger="要不",
        instruction="默认标记为 proposal" * 50,  # 很长，token 必然超 5
    )
    repo.insert_memory_rule(long_rule)
    cfg = AppConfig(memory_max_tokens=5)  # 极小预算
    svc = MemoryService(repo, config=cfg)

    rules = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    judgments = svc.judge_applicability(memories=rules, query="要不")
    injected = svc.build_injection(memories=rules, judgments=judgments)
    assert injected == []  # 超预算 -> 跳过


# ---------- 优先级重排（规格 §6.4）----------

def test_priority_hard_constraint_ranks_first():
    """硬约束优先级高于表达规则，排在注入列表前面。"""
    repo = _make_repo()
    repo.insert_memory_rule(_active_rule(id="mem_speech", rule_type=RuleType.speech_act, confidence=0.99))
    repo.insert_memory_rule(_active_rule(id="mem_hard", rule_type=RuleType.hard_constraint, confidence=0.5))
    svc = MemoryService(repo)

    rules = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    judgments = svc.judge_applicability(memories=rules, query="要不")
    injected = svc.build_injection(memories=rules, judgments=judgments)
    assert injected[0].id == "mem_hard"  # 硬约束排第一


# ---------- 生命周期与反馈降权（规格 §6.5）----------

def test_activate_transitions_candidate_to_active():
    repo = _make_repo()
    rule = MemoryRule(
        id="mem_cand",
        team_id="team_a",
        rule_type=RuleType.speech_act,
        trigger="要不",
        instruction="标记为 proposal",
        status=MemoryStatus.candidate,  # 候选，默认不会被检索
        created_at=_NOW,
    )
    repo.insert_memory_rule(rule)
    svc = MemoryService(repo)

    # 候选态检索不到
    assert svc.retrieve(team_id="team_a", project_id="proj_a", query="要不") == []

    svc.activate("mem_cand")
    got = svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert [m.id for m in got] == ["mem_cand"]


def test_record_use_increments_counts():
    repo = _make_repo()
    repo.insert_memory_rule(_active_rule(id="mem_use"))
    svc = MemoryService(repo)

    svc.record_use(memory_id="mem_use", positive=True, used_at=_NOW)
    svc.record_use(memory_id="mem_use", negative=True, used_at=_NOW)

    rule = repo.get_memory_rule("mem_use")
    assert rule.use_count == 2
    assert rule.positive_count == 1
    assert rule.negative_count == 1
    assert rule.last_used_at == _NOW


def test_pause_removes_from_retrieval():
    repo = _make_repo()
    repo.insert_memory_rule(_active_rule(id="mem_p"))
    svc = MemoryService(repo)

    assert svc.retrieve(team_id="team_a", project_id="proj_a", query="要不") != []
    svc.pause("mem_p")
    assert svc.retrieve(team_id="team_a", project_id="proj_a", query="要不") == []
