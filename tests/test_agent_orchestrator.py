"""agent_orchestrator 端到端测试（Part 6.4 退出条件）。

覆盖规格 §12.2 演示闭环 + §7.1 状态机：
  1. 首次分析：群聊 -> 五桶凭证 + 指标
  2. 纠正 -> 候选记忆（candidate，未被确认前不影响下次运行）
  3. 确认记忆 -> active
  4. 第二次分析：已确认记忆被检索应用，并显示应用理由

Mock provider 下端到端跑通（规格 §3.2 离线 Mock）。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from providers.mock_provider import MockProvider
from repositories.sqlite import SQLiteRepository
from schemas import DecisionType, RuleType
from services.agent_orchestrator import AgentOrchestrator
from tools.extract_decisions import ExtractDecisionsOutput, RawDecision
from tools.propose_memory import ProposeMemoryOutput, RawMemoryCandidate

CST = timezone(timedelta(hours=8))
_NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)

# 规格附录 C / §12.1 演示数据
_DEMO_CHAT = """18:02 A：要不 PPT 做成蓝色？
18:03 B：可以试试。
18:05 C：老师说展示必须使用学院模板。
18:06 A：那晚点再定。"""


def _make_orchestrator() -> tuple[AgentOrchestrator, MockProvider]:
    repo = SQLiteRepository(":memory:")
    repo.init()
    repo.create_team(id="team_a", name="A 组", created_at=_NOW)
    repo.create_project(id="proj_a", team_id="team_a", name="A 项目", created_at=_NOW)

    provider = MockProvider()
    # 注册 extract_decisions 的 builder：根据消息内容返回决策对象
    # 第一次故意把蓝色主题标为 confirmed（可纠正错误，规格 §12.2 第 1 步）
    provider.register_builder(
        ExtractDecisionsOutput,
        lambda prompt: ExtractDecisionsOutput(
            decisions=[
                RawDecision(
                    type=DecisionType.confirmed,
                    summary="PPT 做成蓝色主题",
                    evidence_message_ids=["msg_000"],
                    confidence=0.8,
                    reason="B 说可以试试",
                ),
                RawDecision(
                    type=DecisionType.confirmed,
                    summary="展示使用学院模板",
                    evidence_message_ids=["msg_002"],
                    confidence=0.95,
                    reason="老师要求，硬约束",
                ),
            ]
        ),
    )
    # 注册 propose_memory 的固定响应：返回一条表达规则候选记忆
    # （规格 §12.2 第 3 步「系统生成两条候选记忆，用户确认」）
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
            ]
        ),
    )
    orch = AgentOrchestrator(repo, provider=provider)
    return orch, provider


# ---------- 前向路径：首次分析（规格 §4.1 / §7.1 RECEIVE_TASK -> PRESENT_RESULT）----------

def test_analyze_produces_receipt_and_metrics():
    orch, _ = _make_orchestrator()
    result = orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_001",
        now=_NOW,
    )

    # 五桶凭证非空（规格 §4.1 第 4 步）
    assert result.run_id == "run_001"
    assert len(result.receipt.confirmed) == 2
    # 消息已规范化（规格 §4.1 第 2 步）
    assert len(result.chat_log.messages) == 4
    # 指标面板字段齐全（规格 §3.2 / §11.1）
    assert result.metrics.run_id == "run_001"
    assert result.metrics.latency_ms >= 0
    assert result.metrics.memory_hit_count == 0  # 首次无记忆


def test_analyze_persists_decisions_and_run():
    """分析结果落库可查（规格 §5.3）。"""
    orch, _ = _make_orchestrator()
    orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_001",
        now=_NOW,
    )
    repo = orch._repo
    assert len(repo.list_decisions("proj_a")) == 2
    assert len(repo.list_agent_runs("proj_a")) == 1


# ---------- 反馈路径：纠正 -> 候选记忆（规格 §4.2 / §7.1 RECEIVE_FEEDBACK -> PROPOSE_MEMORY）----------

def test_feedback_produces_candidate_not_yet_active():
    """纠正产生候选记忆，未确认前不影响下次运行（规格 §11.1 / ADR-005）。"""
    from schemas import MemoryStatus

    orch, _ = _make_orchestrator()
    orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_001",
        now=_NOW,
    )

    # 用户把蓝色主题从 confirmed 改为 proposal（规格 §12.2 第 2 步）
    candidates = orch.apply_feedback(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_000",
        before_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"confirmed","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        after_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"proposal","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        user_text="这只是建议，还没定",
        now=_NOW,
    )
    assert len(candidates) >= 1
    # 关键：候选状态固定为 candidate（规格 §6.2 / ADR-005）
    assert all(c.status == MemoryStatus.candidate for c in candidates)


# ---------- 端到端闭环：确认记忆 -> 第二次分析生效（规格 §12.2 第 3-5 步）----------

def test_confirmed_memory_applied_on_second_run():
    """确认后的记忆在第二次分析中被检索应用，并显示应用理由（规格 §4.3 / §12.2）。"""
    orch, _ = _make_orchestrator()
    orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_001",
        now=_NOW,
    )

    candidates = orch.apply_feedback(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_000",
        before_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"confirmed","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        after_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"proposal","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        user_text="这只是建议，还没定",
        now=_NOW,
    )
    # 确认第一条候选（规格 §12.2 第 3 步）
    orch.confirm_memory(candidates[0].id)

    # 第二次分析：记忆应被检索应用（规格 §12.2 第 4-5 步）
    result2 = orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_002",
        now=_NOW,
    )
    assert result2.metrics.memory_hit_count >= 1
    assert len(result2.applied_memories) >= 1
    # 应用理由非空（规格 §4.3「显示应用的规则和证据」）
    assert result2.applied_memories[0].reason


def test_rejected_memory_not_applied():
    """被拒绝的候选不会在后续运行中生效（规格 §4.2 第 4 步）。"""
    orch, _ = _make_orchestrator()
    orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_001",
        now=_NOW,
    )
    candidates = orch.apply_feedback(
        feedback_id="fb_001",
        team_id="team_a",
        project_id="proj_a",
        decision_id="dec_000",
        before_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"confirmed","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        after_json='{"id":"dec_000","team_id":"team_a","project_id":"proj_a",'
        '"type":"proposal","summary":"PPT 做成蓝色主题",'
        '"evidence_message_ids":["msg_000"],"confidence":0.8}',
        now=_NOW,
    )
    orch.reject_memory(candidates[0].id)

    result2 = orch.analyze(
        team_id="team_a",
        project_id="proj_a",
        raw_text=_DEMO_CHAT,
        run_id="run_002",
        now=_NOW,
    )
    assert result2.metrics.memory_hit_count == 0  # 被拒绝，不生效
