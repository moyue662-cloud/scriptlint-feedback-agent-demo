"""propose_memory 工具（规格 7.2）。

调用模型，从用户纠正（修改前 / 后 + 反馈说明）提取候选记忆。
候选记忆必须经用户确认才转为 active（规格 6.2 / ADR-005），
在确认前不得影响下一次运行（规格 11.1）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from providers import LLMProvider
from schemas import FeedbackEvent, MemoryCandidate, MemoryScope, RuleType


class RawMemoryCandidate(BaseModel):
    """模型返回的单条原始候选记忆（不含系统分配字段）。"""

    rule_type: RuleType
    trigger: str
    instruction: str
    scope: MemoryScope = MemoryScope.team
    source_excerpt: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ProposeMemoryOutput(BaseModel):
    """propose_memory 的结构化输出契约（规格 9.2）。"""

    candidates: list[RawMemoryCandidate] = Field(default_factory=list)


def propose_memory(
    *,
    feedback: FeedbackEvent,
    provider: LLMProvider,
    system_prompt: str = "",
) -> list[MemoryCandidate]:
    """修改前 / 后 + 反馈 -> 候选记忆（规格 4.2 / 7.2）。

    模型只负责提取规则语义；id / feedback_id / team_id / project_id
    由本工具统一分配，保证可追溯。
    """
    user_prompt = (
        f"用户纠正了决策 {feedback.decision_id or '(新建)'}：\n"
        f"修改前：{feedback.before_json}\n"
        f"修改后：{feedback.after_json}\n"
        f"用户说明：{feedback.user_text or '(无)'}\n\n"
        "请只提取可在未来重复使用的规则，给出触发条件、动作、来源和反例。"
    )

    result = provider.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=ProposeMemoryOutput,
    )

    candidates: list[MemoryCandidate] = []
    for i, raw in enumerate(result.candidates):
        candidates.append(
            MemoryCandidate(
                id=f"cand_{i:03d}",
                feedback_id=feedback.id,
                team_id=feedback.team_id,
                project_id=feedback.project_id,
                rule_type=raw.rule_type,
                trigger=raw.trigger,
                instruction=raw.instruction,
                scope=raw.scope,
                source_excerpt=raw.source_excerpt,
                confidence=raw.confidence,
            )
        )
    return candidates
