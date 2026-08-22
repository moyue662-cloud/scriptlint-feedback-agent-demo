"""记忆对象与适用性判断模型。

对应规格 5.2 的 MemoryRule、第 6 节记忆系统设计、9.3 节适用性判断输出。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RuleType(str, Enum):
    """记忆类型（规格 6.1）。"""

    speech_act = "speech_act"  # 表达规则
    hard_constraint = "hard_constraint"  # 硬约束
    role = "role"  # 角色规则
    negative_decision = "negative_decision"  # 负面决定
    output_preference = "output_preference"  # 输出偏好（优先级最低）


class MemoryStatus(str, Enum):
    """记忆生命周期状态（规格 6.5 / 图 3）。"""

    candidate = "candidate"  # 候选：模型提出，尚未经用户确认
    active = "active"  # 活跃：已确认，可被检索应用
    paused = "paused"  # 暂停：误用降权后暂停，保留审计
    archived = "archived"  # 归档


class MemoryScope(str, Enum):
    """记忆适用范围（规格 6.3 硬过滤、6.4 优先级）。"""

    team = "team"  # 团队级
    project = "project"  # 项目级


class MemoryRule(BaseModel):
    """一条结构化长期记忆（规格 5.2）。

    写入原则（规格 6.2）：
    - 模型提出的是 candidate，不得直接变成 active。
    - 每条记忆必须有适用范围、来源、置信度和撤销入口。
    """

    id: str = Field(description="记忆 ID，如 mem_007")
    team_id: str = Field(description="所属团队；跨团队默认禁止使用（规格 6.5）")
    project_id: str | None = Field(
        default=None,
        description="所属项目；为空表示团队级规则",
    )
    rule_type: RuleType = Field(description="记忆类型")
    trigger: str = Field(description="触发条件，如「句子包含'要不'」")
    instruction: str = Field(description="动作指令，如「默认标记为 proposal」")
    scope: MemoryScope = Field(default=MemoryScope.team, description="适用范围")
    source_feedback_id: str | None = Field(
        default=None,
        description="来源反馈事件 ID；候选记忆必须可追溯（规格 6.5）",
    )
    source_excerpt: str | None = Field(
        default=None,
        description="来源纠正的原文摘录",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="置信度，0~1",
    )
    status: MemoryStatus = Field(
        default=MemoryStatus.candidate,
        description="生命周期状态",
    )
    created_at: datetime = Field(description="创建时间")
    last_used_at: datetime | None = Field(default=None, description="最近一次被检索应用的时间")
    use_count: int = Field(default=0, ge=0, description="被检索应用的总次数")
    positive_count: int = Field(default=0, ge=0, description="应用后用户认可次数")
    negative_count: int = Field(default=0, ge=0, description="应用后用户指出误用次数")

    @model_validator(mode="after")
    def _scope_project_consistency(self) -> MemoryRule:
        """项目级规则必须带 project_id。"""
        if self.scope == MemoryScope.project and not self.project_id:
            raise ValueError("scope=project 的记忆必须填写 project_id")
        return self


class ApplicabilityDecision(str, Enum):
    """适用性判断结果（规格 6.3 / 9.3）。"""

    apply = "apply"  # 应用
    ignore = "ignore"  # 忽略
    conflict = "conflict"  # 冲突


class ApplicabilityJudgment(BaseModel):
    """对一条记忆在本轮任务中是否适用的判断（规格 9.3）。

    Agent 对每条候选规则输出 apply / ignore / conflict，并附理由与证据。
    不适用的重要规则也要显示忽略原因（规格 4.3）。
    """

    memory_id: str = Field(description="被判断的记忆 ID")
    decision: ApplicabilityDecision = Field(description="apply / ignore / conflict")
    reason: str = Field(description="判断理由，如「本轮消息包含'要不'，且尚无队长确认」")
    evidence_message_ids: list[str] = Field(
        default_factory=list,
        description="支撑该判断的证据消息 ID",
    )
