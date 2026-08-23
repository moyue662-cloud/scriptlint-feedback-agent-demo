"""ScriptLint 第二阶段轻量 Agent 编排器。

编排器不把固定流水线伪装成模型推理：计划是显式的，工具调用有顺序、耗时和
摘要；候选规则必须经过 confirm_rule 才能进入后续审计。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from repositories import SQLiteRepository
from schemas.scriptlint import (
    ScriptAgentMetrics,
    ScriptAgentResult,
    ScriptAuditTask,
    ScriptFeedbackEvent,
    ScriptFeedbackResult,
    ScriptPlanStep,
    ScriptPlanStepStatus,
    ScriptRule,
    ScriptRuleStatus,
    ScriptToolStatus,
    ScriptToolTrace,
)
from services.scriptlint_audit_service import ScriptLintAuditService
from tools.scriptlint_tools import (
    estimate_tokens,
    extract_script_facts,
    plan_feedback_learning,
    plan_script_audit,
    propose_script_rules,
)


class ScriptLintAgent:
    """规划、调用预置工具、沉淀反馈记忆并执行后续审计。"""

    def __init__(self, repo: SQLiteRepository) -> None:
        self._repo = repo
        self._audit = ScriptLintAuditService()

    def analyze(
        self,
        *,
        task: ScriptAuditTask,
        run_id: str,
        now: datetime,
    ) -> ScriptAgentResult:
        started = time.perf_counter()
        plan = plan_script_audit()
        traces: list[ScriptToolTrace] = []

        rules = self._call_tool(
            traces,
            tool_name="retrieve_script_rules",
            input_summary=f"team={task.team_id}, project={task.project_id}, status=active",
            call=lambda: self._repo.list_script_rules(
                team_id=task.team_id,
                project_id=task.project_id,
                status=ScriptRuleStatus.active,
            ),
            summarize=lambda value: f"命中 {len(value)} 条已确认规则",
        )
        self._complete(plan, "retrieve_script_rules")

        facts = self._call_tool(
            traces,
            tool_name="extract_script_facts",
            input_summary=f"task={task.id}, episode={task.episode}, chars={len(task.script_text)}",
            call=lambda: task.facts or extract_script_facts(task),
            summarize=lambda value: f"提取 {len(value)} 个带证据事实",
        )
        self._complete(plan, "extract_script_facts")
        audited_task = task.model_copy(update={"facts": facts})

        audit = self._call_tool(
            traces,
            tool_name="audit_script_rules",
            input_summary=f"facts={len(facts)}, active_rules={len(rules)}",
            call=lambda: self._audit.audit(task=audited_task, rules=rules),
            summarize=lambda value: (
                f"发现 {len(value.findings)} 个问题；"
                f"应用 {value.metrics.memory_applied_count} 条记忆"
            ),
        )
        self._complete(plan, "audit_script_rules")

        self._call_tool(
            traces,
            tool_name="present_audit_result",
            input_summary=f"findings={len(audit.findings)}, traces={len(audit.traces)}",
            call=lambda: {
                "finding_count": len(audit.findings),
                "has_source_trace": bool(rules) and all(
                    bool(rule.source_feedback_id and rule.source_excerpt) for rule in rules
                ),
            },
            summarize=lambda value: (
                f"输出 {value['finding_count']} 个问题；规则来源可追溯="
                f"{value['has_source_trace']}"
            ),
        )
        self._complete(plan, "present_audit_result")

        latency_ms = (time.perf_counter() - started) * 1000
        memory_text = "\n".join(
            f"{rule.requirement}\n{rule.source_excerpt or ''}" for rule in rules
        )
        metrics = ScriptAgentMetrics(
            latency_ms=latency_ms,
            model_call_count=0,
            estimated_input_tokens=estimate_tokens(task.script_text),
            estimated_memory_tokens=estimate_tokens(memory_text),
            estimated_output_tokens=estimate_tokens(audit.model_dump_json()),
            memory_hit_count=audit.metrics.memory_hit_count,
            memory_applied_count=audit.metrics.memory_applied_count,
        )
        result = ScriptAgentResult(
            run_id=run_id,
            task=_model_payload(audited_task),
            retrieved_rules=[_model_payload(item) for item in rules],
            plan=[_model_payload(item) for item in plan],
            tool_traces=[_model_payload(item) for item in traces],
            audit=_model_payload(audit),
            metrics=_model_payload(metrics),
        )
        self._repo.insert_script_agent_result(result, created_at=now)
        return result

    def receive_feedback(
        self,
        *,
        feedback_id: str,
        team_id: str,
        project_id: str,
        original_result: str,
        user_text: str,
        now: datetime,
    ) -> ScriptFeedbackResult:
        plan = plan_feedback_learning()
        traces: list[ScriptToolTrace] = []
        feedback = ScriptFeedbackEvent(
            id=feedback_id,
            team_id=team_id,
            project_id=project_id,
            original_result=original_result,
            user_text=user_text,
            created_at=now,
        )

        self._call_tool(
            traces,
            tool_name="record_script_feedback",
            input_summary=f"feedback={feedback.id}, chars={len(user_text)}",
            call=lambda: self._repo.insert_script_feedback(feedback),
            summarize=lambda _: "反馈原文与原结果已保存",
        )
        self._complete(plan, "record_script_feedback")

        candidates = self._call_tool(
            traces,
            tool_name="propose_script_rule",
            input_summary=f"feedback={feedback.id}",
            call=lambda: propose_script_rules(feedback),
            summarize=lambda value: f"生成 {len(value)} 条候选规则",
        )
        self._complete(plan, "propose_script_rule")

        self._call_tool(
            traces,
            tool_name="store_rule_candidate",
            input_summary=f"candidates={len(candidates)}",
            call=lambda: [self._repo.insert_script_rule(rule) for rule in candidates],
            summarize=lambda _: f"保存 {len(candidates)} 条 candidate；尚未激活",
        )
        self._complete(plan, "store_rule_candidate")

        return ScriptFeedbackResult(
            feedback=_model_payload(feedback),
            candidates=[_model_payload(item) for item in candidates],
            plan=[_model_payload(item) for item in plan],
            tool_traces=[_model_payload(item) for item in traces],
        )

    def confirm_rule(self, rule_id: str) -> ScriptRule:
        rule = self._repo.get_script_rule(rule_id)
        if rule is None:
            raise KeyError(f"候选规则不存在: {rule_id}")
        if rule.status != ScriptRuleStatus.candidate:
            raise ValueError(f"只有 candidate 可以确认，当前状态为 {rule.status.value}")
        self._repo.update_script_rule_status(rule_id, ScriptRuleStatus.active)
        return rule.model_copy(update={"status": ScriptRuleStatus.active})

    def reject_rule(self, rule_id: str) -> ScriptRule:
        rule = self._repo.get_script_rule(rule_id)
        if rule is None:
            raise KeyError(f"候选规则不存在: {rule_id}")
        if rule.status != ScriptRuleStatus.candidate:
            raise ValueError(f"只有 candidate 可以拒绝，当前状态为 {rule.status.value}")
        self._repo.update_script_rule_status(rule_id, ScriptRuleStatus.archived)
        return rule.model_copy(update={"status": ScriptRuleStatus.archived})

    @staticmethod
    def _complete(plan: list[ScriptPlanStep], tool_name: str) -> None:
        for index, step in enumerate(plan):
            if step.tool_name == tool_name:
                plan[index] = step.model_copy(update={"status": ScriptPlanStepStatus.completed})
                return

    @staticmethod
    def _call_tool(
        traces: list[ScriptToolTrace],
        *,
        tool_name: str,
        input_summary: str,
        call: Callable[[], Any],
        summarize: Callable[[Any], str],
    ) -> Any:
        started = time.perf_counter()
        try:
            value = call()
        except Exception as exc:
            traces.append(
                ScriptToolTrace(
                    sequence=len(traces) + 1,
                    tool_name=tool_name,
                    status=ScriptToolStatus.failed,
                    input_summary=input_summary,
                    output_summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            raise
        traces.append(
            ScriptToolTrace(
                sequence=len(traces) + 1,
                tool_name=tool_name,
                status=ScriptToolStatus.succeeded,
                input_summary=input_summary,
                output_summary=summarize(value),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        )
        return value


def _model_payload(value: object) -> object:
    """在 Agent 契约边界消除 Streamlit 热更新造成的模型类身份差异。"""
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="python")
    return value
