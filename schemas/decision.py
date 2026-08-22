"""决策对象模型。

对应规格 5.1 的 DecisionRecord 与 3.2 节的五类对象。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class DecisionType(str, Enum):
    """决策对象的五类（规格 3.2 / 5.1）。

    注：规格 7.3 与 9.1 提到模型在"没有证据 / 不确定"时可输出 unknown。
    为同时满足 5.1 的五类定义与 7.3/9.1 的逃逸出口，此处保留 unknown
    作为第六个取值；它表示"证据不足，无法归类"，落库后通常应转为
    conflict 并附理由，由用户裁定。
    """

    proposal = "proposal"  # 提议
    confirmed = "confirmed"  # 已确认决定
    rejected = "rejected"  # 已否决方案
    task = "task"  # 任务
    conflict = "conflict"  # 冲突 / 待确认
    unknown = "unknown"  # 证据不足，无法归类（规格 7.3 / 9.1 逃逸出口）


class DecisionStatus(str, Enum):
    """决策对象的状态（规格 5.1）。"""

    open = "open"  # 待确认
    confirmed = "confirmed"  # 已确认
    superseded = "superseded"  # 被后续决定取代
    cancelled = "cancelled"  # 已取消


class CreatedBy(str, Enum):
    """决策对象的创建来源。"""

    agent = "agent"  # 由 Agent 识别生成
    user = "user"  # 由用户手动创建或确认


class DecisionRecord(BaseModel):
    """一条可追溯的决策凭证（规格 5.1）。

    每条结论至少绑定一个 evidence_message_id（规格 7.3）。
    没有证据时只能输出 conflict 或 unknown。
    """

    id: str = Field(description="决策对象 ID，如 dec_001")
    team_id: str = Field(description="所属团队")
    project_id: str = Field(description="所属项目")
    type: DecisionType = Field(description="五类对象之一")
    summary: str = Field(description="结论摘要，如「PPT 使用学校官方模板」")
    owner: str | None = Field(default=None, description="负责人")
    deadline: datetime | None = Field(default=None, description="截止时间")
    status: DecisionStatus = Field(default=DecisionStatus.open, description="状态")
    evidence_message_ids: list[str] = Field(
        default_factory=list,
        description="证据消息 ID 列表；每条结论至少绑定一个",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="模型置信度，0~1",
    )
    created_by: CreatedBy = Field(default=CreatedBy.agent, description="创建来源")
    supersedes_id: str | None = Field(
        default=None,
        description="若本决定取代了某条旧决定，填旧决定 ID",
    )
    reason: str | None = Field(
        default=None,
        description="模型判断理由，供前端展开查看（规格 4.1）",
    )

    @model_validator(mode="after")
    def _evidence_required_unless_uncertain(self) -> DecisionRecord:
        """没有证据时只能输出 conflict 或 unknown（规格 7.3）。"""
        if not self.evidence_message_ids and self.type not in {
            DecisionType.conflict,
            DecisionType.unknown,
        }:
            raise ValueError(
                f"DecisionRecord(type={self.type.value}) 必须至少绑定一条 "
                f"evidence_message_id；无证据时只能输出 conflict 或 unknown"
            )
        return self
