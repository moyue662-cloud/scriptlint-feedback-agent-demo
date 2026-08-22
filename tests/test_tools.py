"""P0 工具测试（Part 5 退出条件）。

覆盖规格 7.2 的六个工具：
- normalize_chat    确定性解析
- extract_decisions Mock provider 下结构化输出
- detect_conflicts  确定性冲突检测
- build_receipt     确定性分桶
- propose_memory    Mock provider 下候选记忆
- record_metrics    确定性指标记录
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from providers import MockProvider
from schemas import (
    ApplicabilityDecision,
    ApplicabilityJudgment,
    DataSourceLabel,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
    FeedbackEvent,
    MemoryScope,
    RuleType,
    RunMode,
)
from tools import (
    ConflictReport,
    ReceiptBundle,
    build_receipt,
    detect_conflicts,
    extract_decisions,
    normalize_chat,
    propose_memory,
    record_metrics,
)
from tools.extract_decisions import ExtractDecisionsOutput, RawDecision
from tools.propose_memory import ProposeMemoryOutput, RawMemoryCandidate

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)


# --------------------------------------------------------------------------- #
# normalize_chat
# --------------------------------------------------------------------------- #

def test_normalize_chat_with_timestamps():
    raw = (
        "18:02 A：要不 PPT 做成蓝色？\n"
        "18:03 B：可以试试。\n"
        "18:05 C：老师说展示必须使用学院模板。"
    )
    log = normalize_chat(raw, project_id="p1", source_label=DataSourceLabel.synthetic)
    assert len(log.messages) == 3
    assert log.messages[0].sender == "A"
    assert log.messages[0].sent_at is not None
    assert log.messages[0].sent_at.hour == 18
    assert log.warnings == []
    assert log.source_label == DataSourceLabel.synthetic
    # source_hash 非空且稳定
    assert log.messages[0].source_hash is not None
    assert log.messages[0].id == "msg_000"


def test_normalize_chat_without_timestamps():
    raw = "小李：今晚九点前合并前端。\n小王：收到。"
    log = normalize_chat(raw, project_id="p1")
    assert len(log.messages) == 2
    assert log.messages[0].sent_at is None
    assert log.messages[0].sender == "小李"


def test_normalize_chat_warnings_for_unparseable():
    raw = "A：正常消息\n这行没有说话人\nB：另一条"
    log = normalize_chat(raw, project_id="p1")
    assert len(log.messages) == 2
    assert len(log.warnings) == 1
    assert "无法识别说话人" in log.warnings[0].reason


def test_normalize_chat_empty_lines_skipped():
    raw = "\nA：hi\n\nB：yo\n"
    log = normalize_chat(raw, project_id="p1")
    assert len(log.messages) == 2
    assert log.warnings == []


# --------------------------------------------------------------------------- #
# extract_decisions
# --------------------------------------------------------------------------- #

def test_extract_decisions_with_mock():
    provider = MockProvider()
    provider.register(
        ExtractDecisionsOutput,
        ExtractDecisionsOutput(
            decisions=[
                RawDecision(
                    type=DecisionType.proposal,
                    summary="PPT 做成蓝色",
                    evidence_message_ids=["msg_000"],
                    confidence=0.8,
                    reason="带试探表达",
                ),
                RawDecision(
                    type=DecisionType.confirmed,
                    summary="使用学院模板",
                    evidence_message_ids=["msg_002"],
                    confidence=0.95,
                    reason="硬约束",
                ),
            ]
        ),
    )
    log = normalize_chat(
        "18:02 A：要不 PPT 做成蓝色？\n18:05 C：老师说展示必须使用学院模板。",
        project_id="p1",
    )
    records = extract_decisions(
        messages=log.messages,
        team_id="t1",
        project_id="p1",
        provider=provider,
    )
    assert len(records) == 2
    assert records[0].id == "dec_000"
    assert records[0].team_id == "t1"
    assert records[0].project_id == "p1"
    assert records[0].status == DecisionStatus.open
    assert records[0].evidence_message_ids == ["msg_000"]
    # provider 被调用一次
    assert len(provider.call_log) == 1


def test_extract_decisions_with_memories_in_prompt():
    provider = MockProvider()
    provider.register(ExtractDecisionsOutput, ExtractDecisionsOutput(decisions=[]))
    log = normalize_chat("A：要不试试？", project_id="p1")
    memories = [
        ApplicabilityJudgment(
            memory_id="mem_007",
            decision=ApplicabilityDecision.apply,
            reason="带要不默认 proposal",
            evidence_message_ids=["msg_000"],
        )
    ]
    extract_decisions(
        messages=log.messages,
        memories=memories,
        team_id="t1",
        project_id="p1",
        provider=provider,
    )
    # 确认记忆被拼入 user_prompt
    assert "mem_007" in provider.call_log[0]["user_prompt"]


# --------------------------------------------------------------------------- #
# detect_conflicts
# --------------------------------------------------------------------------- #

def _dec(did, dtype, summary, supersedes_id=None):
    return DecisionRecord(
        id=did,
        team_id="t1",
        project_id="p1",
        type=dtype,
        summary=summary,
        evidence_message_ids=["msg_x"],
        supersedes_id=supersedes_id,
    )


def test_detect_conflicts_supersede():
    new = [_dec("dec_1", DecisionType.confirmed, "蓝色主题", supersedes_id="dec_0")]
    report = detect_conflicts(new_decisions=new)
    assert len(report.items) == 1
    assert report.items[0].conflict_type == "supersede"


def test_detect_conflicts_contradiction_with_history():
    history = [_dec("dec_0", DecisionType.confirmed, "蓝色主题方案")]
    new = [_dec("dec_1", DecisionType.rejected, "蓝色主题方案不用了")]
    report = detect_conflicts(new_decisions=new, history=history)
    assert any(i.conflict_type == "contradiction" for i in report.items)


def test_detect_conflicts_duplicate_confirmed():
    history = [_dec("dec_0", DecisionType.confirmed, "用学院模板做PPT")]
    new = [_dec("dec_1", DecisionType.confirmed, "用学院模板做PPT展示")]
    report = detect_conflicts(new_decisions=new, history=history)
    assert any(i.conflict_type == "duplicate" for i in report.items)


def test_detect_conflicts_none_when_unrelated():
    history = [_dec("dec_0", DecisionType.confirmed, "完全不同的主题")]
    new = [_dec("dec_1", DecisionType.rejected, "另一个不相关的事")]
    report = detect_conflicts(new_decisions=new, history=history)
    assert len(report.items) == 0


def test_detect_conflicts_between_new_decisions():
    new = [
        _dec("dec_0", DecisionType.confirmed, "蓝色主题方案"),
        _dec("dec_1", DecisionType.rejected, "蓝色主题方案"),
    ]
    report = detect_conflicts(new_decisions=new)
    assert any(i.conflict_type == "contradiction" for i in report.items)


# --------------------------------------------------------------------------- #
# build_receipt
# --------------------------------------------------------------------------- #

def test_build_receipt_buckets_and_evidence():
    decisions = [
        _dec("dec_0", DecisionType.confirmed, "用学院模板"),
        _dec("dec_1", DecisionType.proposal, "蓝色主题", supersedes_id=None),
        _dec("dec_2", DecisionType.task, "小李合并前端"),
    ]
    log = normalize_chat(
        "A：老师说用学院模板\nB：要不蓝色主题？\n小李：我合并前端",
        project_id="p1",
    )
    # 把证据指向真实消息
    decisions[0].evidence_message_ids = [log.messages[0].id]
    decisions[1].evidence_message_ids = [log.messages[1].id]
    decisions[2].evidence_message_ids = [log.messages[2].id]

    bundle = build_receipt(decisions=decisions, messages=log.messages)
    assert isinstance(bundle, ReceiptBundle)
    assert len(bundle.confirmed) == 1
    assert len(bundle.proposal) == 1
    assert len(bundle.task) == 1
    # 证据绑定到真实消息内容
    assert bundle.confirmed[0].evidence[0]["sender"] == "A"
    assert "学院模板" in bundle.confirmed[0].evidence[0]["content"]


def test_build_receipt_missing_evidence_shown_as_none():
    decisions = [_dec("dec_0", DecisionType.confirmed, "x")]
    decisions[0].evidence_message_ids = ["msg_nonexistent"]
    bundle = build_receipt(decisions=decisions, messages=[])
    assert bundle.confirmed[0].evidence[0]["sender"] is None


# --------------------------------------------------------------------------- #
# propose_memory
# --------------------------------------------------------------------------- #

def test_propose_memory_with_mock():
    provider = MockProvider()
    provider.register(
        ProposeMemoryOutput,
        ProposeMemoryOutput(
            candidates=[
                RawMemoryCandidate(
                    rule_type=RuleType.speech_act,
                    trigger="句子包含'要不'",
                    instruction="默认标记为 proposal",
                    scope=MemoryScope.team,
                    source_excerpt="这只是建议",
                    confidence=0.9,
                )
            ]
        ),
    )
    fb = FeedbackEvent(
        id="fb_001",
        team_id="t1",
        project_id="p1",
        decision_id="dec_0",
        before_json='{"type":"confirmed"}',
        after_json='{"type":"proposal"}',
        user_text="这只是建议，还没定",
        created_at=NOW,
    )
    candidates = propose_memory(feedback=fb, provider=provider)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.id == "cand_000"
    assert c.feedback_id == "fb_001"
    assert c.team_id == "t1"
    assert c.project_id == "p1"
    assert c.rule_type == RuleType.speech_act
    assert c.scope == MemoryScope.team


def test_propose_memory_empty_candidates():
    provider = MockProvider()
    provider.register(ProposeMemoryOutput, ProposeMemoryOutput(candidates=[]))
    fb = FeedbackEvent(
        id="fb_002",
        team_id="t1",
        project_id="p1",
        before_json="{}",
        after_json="{}",
        created_at=NOW,
    )
    candidates = propose_memory(feedback=fb, provider=provider)
    assert candidates == []


# --------------------------------------------------------------------------- #
# record_metrics
# --------------------------------------------------------------------------- #

def test_record_metrics_basic():
    run = record_metrics(
        run_id="run_001",
        team_id="t1",
        project_id="p1",
        latency_ms=420,
        input_tokens=500,
        memory_tokens=180,
        output_tokens=200,
        memory_hit_count=3,
        memory_applied_count=2,
        now=NOW,
    )
    assert run.id == "run_001"
    assert run.mode == RunMode.decisionpatch
    assert run.latency_ms == 420
    assert run.memory_tokens == 180
    assert run.memory_tokens <= 300  # 规格目标


def test_record_metrics_custom_mode():
    run = record_metrics(
        run_id="run_002",
        team_id="t1",
        project_id="p1",
        latency_ms=100,
        mode=RunMode.no_memory,
        now=NOW,
    )
    assert run.mode == RunMode.no_memory
    assert run.input_tokens == 0
