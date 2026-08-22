"""运行 ScriptLint 第二阶段：真实反馈门禁 + Agent 工具轨迹。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from repositories import SQLiteRepository
from schemas.scriptlint import ScriptAuditTask
from services.scriptlint_agent import ScriptLintAgent


NOW = datetime(2026, 8, 22, 14, 0, tzinfo=timezone(timedelta(hours=8)))


def _summary(label: str, result) -> dict:
    return {
        "stage": label,
        "active_memory_hits": result.metrics.memory_hit_count,
        "applied_memories": result.metrics.memory_applied_count,
        "findings": [finding.finding_type.value for finding in result.audit.findings],
        "tool_trace": [
            {
                "sequence": trace.sequence,
                "tool": trace.tool_name,
                "status": trace.status.value,
                "output": trace.output_summary,
            }
            for trace in result.tool_traces
        ],
        "estimated_memory_tokens": result.metrics.estimated_memory_tokens,
        "model_calls": result.metrics.model_call_count,
    }


def run_demo() -> dict:
    repo = SQLiteRepository(":memory:")
    repo.init()
    agent = ScriptLintAgent(repo)
    task = ScriptAuditTask(
        id="task_episode_03",
        team_id="team_scriptlint",
        project_id="project_rainy_store",
        episode=3,
        title="第3集身份揭示审计",
        script_text="场景：雨夜便利店。\n女主：原来你就是集团继承人。",
    )

    before = agent.analyze(task=task, run_id="run_before_feedback", now=NOW)
    feedback = agent.receive_feedback(
        feedback_id="feedback_001",
        team_id=task.team_id,
        project_id=task.project_id,
        original_result="系统未发现问题",
        user_text="这次判断不对。女主在第1到3集不能知道男主是集团继承人，这条规则只限制女主。",
        now=NOW,
    )
    before_confirmation = agent.analyze(
        task=task,
        run_id="run_candidate_not_active",
        now=NOW,
    )
    confirmed = agent.confirm_rule(feedback.candidates[0].id)
    after_confirmation = agent.analyze(
        task=task,
        run_id="run_after_confirmation",
        now=NOW,
    )

    output = {
        "data_label": "人工构造 · Demo",
        "before_feedback": _summary("首次审计：无记忆", before),
        "feedback_learning": {
            "feedback_id": feedback.feedback.id,
            "candidate_id": feedback.candidates[0].id,
            "candidate_status": feedback.candidates[0].status.value,
            "source_excerpt": feedback.candidates[0].source_excerpt,
            "tool_trace": [trace.tool_name for trace in feedback.tool_traces],
        },
        "before_confirmation": _summary("候选未确认：仍不生效", before_confirmation),
        "confirmation": {
            "rule_id": confirmed.id,
            "status": confirmed.status.value,
        },
        "after_confirmation": _summary("确认后：后续任务应用记忆", after_confirmation),
    }
    repo.close()
    return output


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
