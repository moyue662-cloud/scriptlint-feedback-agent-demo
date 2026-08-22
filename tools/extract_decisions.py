"""extract_decisions 工具（规格 7.2）。

调用模型，把消息 + 候选记忆转换为决策对象列表。
所有输出符合 JSON Schema（规格 7.3），每条结论至少绑定一个
evidence_message_id；没有证据时只能输出 conflict 或 unknown。
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, Field

from providers import LLMProvider
from schemas import (
    ApplicabilityJudgment,
    CreatedBy,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
    Message,
)


class RawDecision(BaseModel):
    """模型返回的单条原始决策（不含系统分配的 id / team_id / project_id）。"""

    type: DecisionType
    summary: str
    owner: str | None = None
    deadline: datetime | None = None
    evidence_message_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str | None = None


class ExtractDecisionsOutput(BaseModel):
    """extract_decisions 的结构化输出契约（规格 7.3）。"""

    decisions: list[RawDecision] = Field(default_factory=list)


def extract_decisions(
    *,
    messages: Sequence[Message],
    memories: Sequence[ApplicabilityJudgment] | None = None,
    team_id: str,
    project_id: str,
    provider: LLMProvider,
    system_prompt: str = "",
) -> list[DecisionRecord]:
    """消息 + 候选记忆 -> 决策对象列表（规格 4.1 / 7.2）。

    模型只负责语义判断与证据绑定；id / team_id / project_id / status /
    created_by 由本工具统一分配，保证落库字段一致。
    """
    msg_lines = [f"[{m.id}] {m.sender}: {m.content}" for m in messages]
    mem_lines: list[str] = []
    if memories:
        for j in memories:
            mem_lines.append(f"记忆 {j.memory_id} ({j.decision.value}): {j.reason}")

    user_prompt = (
        "以下是群聊消息：\n" + "\n".join(msg_lines) + "\n\n"
        + ("适用记忆：\n" + "\n".join(mem_lines) + "\n\n" if mem_lines else "")
        + "请识别其中的提议、已确认、已否决、任务、冲突。"
        + "每条结论必须引用消息 ID；不确定时输出 conflict。"
    )

    result = provider.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=ExtractDecisionsOutput,
    )

    records: list[DecisionRecord] = []
    for i, raw in enumerate(result.decisions):
        records.append(
            DecisionRecord(
                id=f"dec_{i:03d}",
                team_id=team_id,
                project_id=project_id,
                type=raw.type,
                summary=raw.summary,
                owner=raw.owner,
                deadline=raw.deadline,
                status=DecisionStatus.open,
                evidence_message_ids=raw.evidence_message_ids,
                confidence=raw.confidence,
                created_by=CreatedBy.agent,
                reason=raw.reason,
            )
        )
    return records
