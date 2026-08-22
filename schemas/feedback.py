"""反馈事件与候选记忆模型。

对应规格 5.3 的 feedback_events 表、4.2 节"纠正与记忆"流程。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .memory import MemoryScope, RuleType


class FeedbackEvent(BaseModel):
    """一次用户纠正事件（规格 5.3 / 4.2）。

    保存修改前后的决策对象快照与用户补充说明，用于：
    - 提取候选记忆（propose_memory）
    - 审计与回溯
    """

    id: str = Field(description="反馈事件 ID，如 fb_003")
    team_id: str = Field(description="所属团队")
    project_id: str = Field(description="所属项目")
    decision_id: str | None = Field(
        default=None,
        description="被纠正的决策对象 ID；新建型反馈可为空",
    )
    before_json: str = Field(description="修改前的 DecisionRecord 序列化 JSON")
    after_json: str = Field(description="修改后的 DecisionRecord 序列化 JSON")
    user_text: str | None = Field(
        default=None,
        description="用户补充的纠正说明，如「这只是建议，还没定」",
    )
    created_at: datetime = Field(description="反馈时间")


class MemoryCandidate(BaseModel):
    """模型从反馈中提取的候选记忆（规格 4.2 / 6.2）。

    候选记忆必须经用户确认后才转为 active（规格 6.2 / ADR-005）。
    在确认前不得影响下一次运行（规格 11.1）。
    """

    id: str = Field(description="候选记忆 ID")
    feedback_id: str = Field(description="来源反馈事件 ID")
    team_id: str = Field(description="所属团队")
    project_id: str | None = Field(default=None, description="所属项目；为空表示团队级")
    rule_type: RuleType = Field(description="记忆类型")
    trigger: str = Field(description="触发条件")
    instruction: str = Field(description="动作指令")
    scope: MemoryScope = Field(default=MemoryScope.team, description="适用范围")
    source_excerpt: str | None = Field(default=None, description="来源纠正的原文摘录")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="模型给出的置信度",
    )
    # 候选记忆状态固定为 candidate，确认后由 memory_service 转为 active
