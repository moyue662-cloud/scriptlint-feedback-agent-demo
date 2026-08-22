"""运行指标模型。

对应规格 5.3 的 agent_runs 表、第 10 节评测方案。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RunMode(str, Enum):
    """三组对照模式（规格 10.3）。赛题 4 的技术结论必须来自该对照。"""

    no_memory = "no_memory"  # 无记忆：只分析当前群聊
    full_history = "full_history"  # 全历史：把所有历史拼入上下文
    decisionpatch = "decisionpatch"  # DecisionPatch：结构化记忆检索与限额注入


class AgentRun(BaseModel):
    """一次 Agent 运行的成本与速度指标（规格 5.3 / 10.2）。

    指标面板需展示 token、延迟和命中详情（规格 3.2 / 11.1）。
    """

    id: str = Field(description="运行 ID")
    team_id: str = Field(description="所属团队")
    project_id: str = Field(description="所属项目")
    mode: RunMode = Field(default=RunMode.decisionpatch, description="对照模式")
    latency_ms: int = Field(ge=0, description="端到端耗时（毫秒）")
    input_tokens: int = Field(default=0, ge=0, description="输入 token 数")
    memory_tokens: int = Field(
        default=0,
        ge=0,
        description="注入的长期记忆 token 数；目标 ≤ 300（规格 10.2）",
    )
    output_tokens: int = Field(default=0, ge=0, description="输出 token 数")
    memory_hit_count: int = Field(
        default=0,
        ge=0,
        description="本轮检索命中的记忆条数",
    )
    memory_applied_count: int = Field(
        default=0,
        ge=0,
        description="本轮实际应用（apply）的记忆条数",
    )
    created_at: datetime = Field(description="运行时间")
