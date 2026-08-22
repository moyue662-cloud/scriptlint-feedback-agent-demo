"""feedback_service 单元测试（Part 6.2）。

覆盖规格 §4.2（纠正与记忆）、§6.2（写入原则）、ADR-005（记忆必须人工确认）。
核心断言：候选记忆未经确认不会被检索应用（规格 §11.1）。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from providers.mock_provider import MockProvider
from repositories.sqlite import SQLiteRepository
from schemas import (
    CreatedBy,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
    MemoryStatus,
    RuleType,
)
from services.feedback_service import FeedbackService
from tools.propose_memory import ProposeMemoryOutput, RawMemoryCandidate

CST = timezone(timedelta(hours=8))
_NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)


def _make_repo() -> SQLiteRepository:
    repo = SQLiteRepository(":memory:")
    repo.init()
    repo.create_team(id="team_a", name="A 组", created_at=_NOW)
    repo.create_project(id="proj_a", team_id="team_a", name="A 项目", created_at=_NOW)
    return repo


def _make_provider_with_candidates() -> MockProvider:
    """注册一个返回两条候选记忆的 Mock provider。"""
    provider = MockProvider()
    provider.register(
        ProposeMemoryOutput,
        ProposeMemoryOutput(
            candidates=[
                RawMemoryCandidate(
                    rule_type=RuleType.speech_act,
                    trigger="句子包含'要不'",
                    instruction="默认标记为 proposal，不得直接标记为 confirmed",
                    source_excerpt="这只是建议，还没定",
                    confidence=0.9,
                ),
                RawMemoryCandidate(
                    rule_type=RuleType.hard_constraint,
                    trigger="句子包含'老师'且包含'必须'",
                    instruction="标记为 confirmed，属于硬约束",
                    source_excerpt="老师说展示必须使用学院模板",
                    confidence=0.95,
                ),
            ]
        ),
    )
    return provider


def _before_decision() -> DecisionRecord:
    """修改前：被误标为 confirmed 的蓝色主题。"""
    return DecisionRecord(
        id="dec_001",
        team_id="team_a",
        project_id="proj_a",
        type=DecisionType.confirmed,
        summary="PPT 做成蓝色主题",
        evidence_message_ids=["msg_001"],
        confidence=0.8,
    )


def _after_decision() -> DecisionRecord:
    """修改后：纠正为 proposal。"""
    return DecisionRecord(
        id="dec_001",
        team_id="team_a",
        project_id="proj_a",
        type=DecisionType.proposal,
        summary="PPT 做成蓝色主题",
        evidence_message_ids=["msg_001"],
        confidence=0.8,
        created_by=CreatedBy.user,
    )


# ---------- 记录纠正（规格 §4.2 第 1 步）----------

def test_record_correction_persists_feedback_event():
    repo = _make_repo()
    svc = FeedbackService(repo, provider=MockProvider())

    fb = svc.record_correction(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_001",
        before=_before_decision(),
        after=_after_decision(),
        user_text="这只是建议，还没定",
        now=_NOW,
    )
    assert fb.id == "fb_001"
    assert fb.user_text == "这只是建议，还没定"

    # 落库可读回
    got = repo.get_feedback_event("fb_001")
    assert got is not None
    assert got.decision_id == "dec_001"


# ---------- 提取候选记忆（规格 §4.2 第 2 步 / §6.2）----------

def test_propose_candidates_saves_as_candidate():
    repo = _make_repo()
    svc = FeedbackService(repo, provider=_make_provider_with_candidates())

    fb = svc.record_correction(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_001",
        before=_before_decision(),
        after=_after_decision(),
        user_text="这只是建议，还没定",
        now=_NOW,
    )
    candidates = svc.propose_candidates(feedback=fb)

    assert len(candidates) == 2
    # 关键：候选记忆状态固定为 candidate（规格 §6.2 / ADR-005）
    assert all(c.status == MemoryStatus.candidate for c in candidates)
    # 来源可追溯
    assert all(c.source_feedback_id == "fb_001" for c in candidates)
    # 落库可读回
    assert repo.get_memory_rule(candidates[0].id) is not None


# ---------- ADR-005 核心：候选未确认不被检索 ----------

def test_candidate_not_retrievable_until_confirmed():
    """候选记忆未经确认不会影响下一次运行（规格 §11.1 / ADR-005）。"""
    from services.memory_service import MemoryService

    repo = _make_repo()
    provider = _make_provider_with_candidates()
    fb_svc = FeedbackService(repo, provider=provider)
    mem_svc = MemoryService(repo)

    fb = fb_svc.record_correction(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_001",
        before=_before_decision(),
        after=_after_decision(),
        user_text="这只是建议，还没定",
        now=_NOW,
    )
    candidates = fb_svc.propose_candidates(feedback=fb)
    assert len(candidates) == 2

    # 确认前：检索不到任何候选记忆（candidate 不在 active 里）
    got = mem_svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert got == []

    # 确认第一条
    fb_svc.confirm_candidate(candidates[0].id)

    # 确认后：第一条可被检索
    got = mem_svc.retrieve(team_id="team_a", project_id="proj_a", query="要不")
    assert [m.id for m in got] == [candidates[0].id]


# ---------- 拒绝候选（规格 §4.2 第 4 步）----------

def test_reject_candidate_archives():
    repo = _make_repo()
    svc = FeedbackService(repo, provider=_make_provider_with_candidates())

    fb = svc.record_correction(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_001",
        before=_before_decision(),
        after=_after_decision(),
        now=_NOW,
    )
    candidates = svc.propose_candidates(feedback=fb)

    svc.reject_candidate(candidates[0].id)
    rule = repo.get_memory_rule(candidates[0].id)
    assert rule.status == MemoryStatus.archived  # 归档保留审计，不进 active
