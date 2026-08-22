"""离线演示 Provider。

这个 Provider 只用于本地 demo：用一组可解释的确定性启发式生成已经通过
Pydantic schema 的结构化结果。它不改变真正的 Provider 契约，也不把演示
数据伪装成线上模型能力。
"""
from __future__ import annotations

import re
from datetime import datetime

from schemas import DecisionType, RuleType
from tools.extract_decisions import ExtractDecisionsOutput, RawDecision
from tools.propose_memory import ProposeMemoryOutput, RawMemoryCandidate

from .mock_provider import MockProvider


_MESSAGE_RE = re.compile(r"\[(msg_\d+)\]\s+([^:：]+)[:：]\s*(.+)")
_DEADLINE_RE = re.compile(r"(\d{1,2})[点时](?:前|之前)?")


def build_demo_provider() -> MockProvider:
    """返回稳定的离线 Provider，供 Streamlit 录屏和无网演示使用。"""
    provider = MockProvider()
    provider.register_builder(ExtractDecisionsOutput, _extract_demo_decisions)
    provider.register_builder(ProposeMemoryOutput, _propose_demo_memories)
    return provider


def _extract_demo_decisions(prompt: str) -> ExtractDecisionsOutput:
    """从 demo prompt 生成五类决策凭证。

    首次运行保留一个可纠正的演示误判：试探表达会先显示为 confirmed；
    当 prompt 含有已应用的 speech_act 记忆时，再显示为 proposal。
    """
    rows = _MESSAGE_RE.findall(prompt)
    has_applied_memory = "适用记忆：" in prompt and "apply" in prompt
    decisions: list[RawDecision] = []

    for msg_id, sender, content in rows:
        normalized = content.strip()
        if not normalized:
            continue

        dtype, reason = _classify_line(normalized, has_applied_memory)
        if dtype is None:
            continue

        deadline = None
        deadline_match = _DEADLINE_RE.search(normalized)
        if dtype == DecisionType.task and deadline_match:
            hour = int(deadline_match.group(1))
            deadline = datetime(2026, 8, 20, hour, 0)

        decisions.append(
            RawDecision(
                type=dtype,
                summary=_summary(normalized),
                owner=sender.strip() if dtype == DecisionType.task else None,
                deadline=deadline,
                evidence_message_ids=[msg_id],
                confidence=_confidence(dtype, normalized),
                reason=reason,
            )
        )

    return ExtractDecisionsOutput(decisions=decisions)


def _classify_line(
    content: str, has_applied_memory: bool
) -> tuple[DecisionType | None, str]:
    """按明确的中文表达做最小、可读的离线分类。"""
    if any(token in content for token in ("不用", "不采用", "否决", "取消", "不做")):
        return DecisionType.rejected, "出现明确否决或取消表达"

    if any(token in content for token in ("今晚", "明天", "负责", "交给", "提交", "合并", "截止")):
        return DecisionType.task, "包含可执行动作或负责人线索"

    if any(token in content for token in ("晚点再定", "再确认", "待确认", "还没定", "不确定", "冲突")):
        return DecisionType.conflict, "同时存在行动与未确认信号"

    if any(token in content for token in ("老师", "必须", "按学院模板", "统一", "确定", "就用")):
        return DecisionType.confirmed, "出现明确确认或外部硬约束"

    if any(token in content for token in ("要不", "可以试试", "或许", "建议", "不如")):
        if has_applied_memory:
            return DecisionType.proposal, "已应用表达规则：试探表达默认是提议"
        return DecisionType.confirmed, "演示中的待纠正判断：把试探表达暂标为已确认"

    return None, ""


def _summary(content: str) -> str:
    """保持卡片短而可读，证据仍保留完整原文。"""
    summary = content.rstrip("。！？!? ")
    return summary[:72] + ("…" if len(summary) > 72 else "")


def _confidence(dtype: DecisionType, content: str) -> float:
    if dtype == DecisionType.confirmed and any(x in content for x in ("老师", "必须")):
        return 0.96
    if dtype == DecisionType.task:
        return 0.9
    if dtype == DecisionType.conflict:
        return 0.84
    if dtype == DecisionType.rejected:
        return 0.92
    return 0.78


def _propose_demo_memories(prompt: str) -> ProposeMemoryOutput:
    """从一次纠正稳定地产生最多两条候选规则。"""
    candidates = [
        RawMemoryCandidate(
            rule_type=RuleType.speech_act,
            trigger="句子包含'要不'或'可以试试'",
            instruction="默认标记为 proposal，不得直接标记为 confirmed",
            source_excerpt="这只是建议，还没定",
            confidence=0.92,
        )
    ]
    if "老师" in prompt or "必须" in prompt or "学院模板" in prompt:
        candidates.append(
            RawMemoryCandidate(
                rule_type=RuleType.hard_constraint,
                trigger="句子包含'老师'且包含'必须'",
                instruction="标记为 confirmed，并在结果中显示为硬约束",
                source_excerpt="老师要求展示必须使用学院模板",
                confidence=0.96,
            )
        )
    return ProposeMemoryOutput(candidates=candidates)
