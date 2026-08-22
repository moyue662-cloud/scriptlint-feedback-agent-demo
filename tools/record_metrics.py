"""record_metrics 工具（规格 7.2）。

确定性，不调用模型。把本次运行统计组装为 agent_run 记录，
供指标面板展示 token、延迟和命中详情（规格 3.2 / 11.1）。
"""
from __future__ import annotations

from datetime import datetime

from schemas import AgentRun, RunMode


def record_metrics(
    *,
    run_id: str,
    team_id: str,
    project_id: str,
    latency_ms: int,
    input_tokens: int = 0,
    memory_tokens: int = 0,
    output_tokens: int = 0,
    memory_hit_count: int = 0,
    memory_applied_count: int = 0,
    mode: RunMode = RunMode.decisionpatch,
    now: datetime,
) -> AgentRun:
    """本次运行统计 -> agent_run 记录（规格 7.2 / 10.2）。"""
    return AgentRun(
        id=run_id,
        team_id=team_id,
        project_id=project_id,
        mode=mode,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        memory_tokens=memory_tokens,
        output_tokens=output_tokens,
        memory_hit_count=memory_hit_count,
        memory_applied_count=memory_applied_count,
        created_at=now,
    )
