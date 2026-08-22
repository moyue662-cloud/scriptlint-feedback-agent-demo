"""Agent 编排：状态机（规格 §7.1）。

把前面所有层串成端到端核心闭环：
  RECEIVE_TASK -> NORMALIZE_MESSAGES -> PLAN -> RETRIEVE_MEMORY
  -> EXTRACT_CANDIDATES -> DETECT_CONFLICTS -> BUILD_DECISION_RECEIPTS
  -> VALIDATE_SCHEMA -> PRESENT_RESULT
  -> RECEIVE_FEEDBACK -> PROPOSE_MEMORY -> USER_CONFIRMATION -> STORE_MEMORY

前向路径（RECEIVE_TASK -> PRESENT_RESULT）由 analyze() 完成；
反馈路径（RECEIVE_FEEDBACK -> STORE_MEMORY）由 apply_feedback() 完成，
两者之间隔着用户交互，故分离（规格图 2「反馈写入与结果生成分离」）。

退出条件（Part 6）：Mock provider 下端到端核心闭环跑通。
"""
from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel, Field

from config import AppConfig, CONFIG
from providers import LLMProvider
from repositories.sqlite import SQLiteRepository
from schemas import ChatLog, MemoryRule
from services.memory_service import MemoryService
from tools.build_receipt import ReceiptBundle, build_receipt
from tools.detect_conflicts import ConflictReport, detect_conflicts
from tools.extract_decisions import extract_decisions
from tools.normalize_chat import normalize_chat
from tools.record_metrics import record_metrics


# --------------------------------------------------------------------------- #
# 编排输出契约（前端 Kimi 依赖此 JSON 结构，规格 §16.2）
# --------------------------------------------------------------------------- #


class AppliedMemory(BaseModel):
    """本轮被应用的记忆及其理由（规格 §4.3「显示应用的规则和证据」）。"""

    memory_id: str
    rule_type: str
    trigger: str
    instruction: str
    reason: str


class IgnoredMemory(BaseModel):
    """本轮被忽略的重要记忆及其原因（规格 §4.3「不适用的重要规则也显示忽略原因」）。"""

    memory_id: str
    rule_type: str
    trigger: str
    reason: str


class AnalysisResult(BaseModel):
    """一次前向分析的完整结果（规格 §4.1 / §4.3 / §3.2 指标面板）。"""

    run_id: str
    chat_log: ChatLog
    receipt: ReceiptBundle
    conflicts: ConflictReport
    applied_memories: list[AppliedMemory] = Field(default_factory=list)
    ignored_memories: list[IgnoredMemory] = Field(default_factory=list)
    metrics: "AgentRunRef"  # 见下方前向引用


class AgentRunRef(BaseModel):
    """指标摘要（规格 §3.2 指标面板：token、延迟、命中详情）。"""

    run_id: str
    latency_ms: int
    input_tokens: int
    memory_tokens: int
    output_tokens: int
    memory_hit_count: int
    memory_applied_count: int


# 解决 AnalysisResult.metrics 的前向引用
AnalysisResult.model_rebuild()


class AgentOrchestrator:
    """DecisionPatch 核心闭环编排器（规格 §7.1 状态机）。

    依赖 Repository（持久）、Provider（模型）、MemoryService（检索注入）、
    FeedbackService（纠正→记忆）。Mock provider 下可端到端跑通。
    """

    def __init__(
        self,
        repo: SQLiteRepository,
        *,
        provider: LLMProvider,
        config: AppConfig | None = None,
    ) -> None:
        self._repo = repo
        self._provider = provider
        self._cfg = config or CONFIG
        self._memory = MemoryService(repo, config=config, provider=provider)
        # FeedbackService 延迟导入，避免循环依赖
        from services.feedback_service import FeedbackService

        self._feedback = FeedbackService(repo, provider=provider)

    # -- 前向路径：RECEIVE_TASK -> PRESENT_RESULT --------------------------- #

    def analyze(
        self,
        *,
        team_id: str,
        project_id: str,
        raw_text: str,
        run_id: str,
        now: datetime,
        source_label=None,
        extract_system_prompt: str = "",
    ) -> AnalysisResult:
        """前向核心闭环（规格 §7.1 / §4.1）。

        返回前端展示所需的全部结构：消息、五桶凭证、冲突、
        应用/忽略记忆及理由、运行指标。
        """
        t0 = time.perf_counter()

        # RECEIVE_TASK -> NORMALIZE_MESSAGES（规格 §4.1 第 1-2 步）
        chat_log = normalize_chat(
            raw_text, project_id=project_id, source_label=source_label
        )
        self._repo.insert_messages(chat_log.messages)

        # PLAN（隐式）-> RETRIEVE_MEMORY（规格 §6.3 / §4.3 第 1-2 步）
        query = "\n".join(m.content for m in chat_log.messages)
        memories = self._memory.retrieve(
            team_id=team_id, project_id=project_id, query=query
        )
        judgments = self._memory.judge_applicability(memories=memories, query=query)
        injected = self._memory.build_injection(
            memories=memories, judgments=judgments
        )

        # EXTRACT_CANDIDATES（规格 §4.1 第 3 步 / §7.2）
        decisions = extract_decisions(
            messages=chat_log.messages,
            memories=judgments,
            team_id=team_id,
            project_id=project_id,
            provider=self._provider,
            system_prompt=extract_system_prompt,
        )
        for d in decisions:
            self._repo.insert_decision(d, created_at=now)

        # DETECT_CONFLICTS（规格 §7.2 / §6.4）
        history = self._repo.list_decisions(project_id)
        conflicts = detect_conflicts(new_decisions=decisions, history=history)

        # BUILD_DECISION_RECEIPTS（规格 §4.1 第 4 步 / §7.2）
        receipt = build_receipt(decisions=decisions, messages=chat_log.messages)

        # VALIDATE_SCHEMA —— 已由 Pydantic 在各工具出口保证（规格 §7.3）

        # 记录记忆使用（规格 §6.5）
        for rule in injected:
            self._memory.record_use(memory_id=rule.id, positive=False, used_at=now)

        # 应用/忽略记忆的可解释结构（规格 §4.3）
        applied, ignored = _split_judgments(memories, judgments)

        # PRESENT_RESULT + 指标（规格 §3.2 / §11.1）
        latency_ms = int((time.perf_counter() - t0) * 1000)
        run = record_metrics(
            run_id=run_id,
            team_id=team_id,
            project_id=project_id,
            latency_ms=latency_ms,
            memory_hit_count=len(memories),
            memory_applied_count=len(injected),
            now=now,
        )
        self._repo.insert_agent_run(run)

        return AnalysisResult(
            run_id=run_id,
            chat_log=chat_log,
            receipt=receipt,
            conflicts=conflicts,
            applied_memories=applied,
            ignored_memories=ignored,
            metrics=AgentRunRef(
                run_id=run_id,
                latency_ms=run.latency_ms,
                input_tokens=run.input_tokens,
                memory_tokens=run.memory_tokens,
                output_tokens=run.output_tokens,
                memory_hit_count=run.memory_hit_count,
                memory_applied_count=run.memory_applied_count,
            ),
        )

    # -- 反馈路径：RECEIVE_FEEDBACK -> STORE_MEMORY ------------------------- #

    def apply_feedback(
        self,
        *,
        feedback_id: str,
        team_id: str,
        project_id: str,
        decision_id: str | None,
        before_json: str,
        after_json: str,
        user_text: str | None = None,
        now: datetime,
        propose_system_prompt: str = "",
    ):
        """纠正 -> 候选记忆（规格 §4.2 / §7.1 RECEIVE_FEEDBACK -> PROPOSE_MEMORY）。

        候选记忆落库为 candidate，未经用户确认不会被检索应用
        （规格 §6.2 / §11.1 / ADR-005）。
        """
        from schemas import DecisionRecord

        before = DecisionRecord.model_validate_json(before_json)
        after = DecisionRecord.model_validate_json(after_json)

        fb = self._feedback.record_correction(
            feedback_id=feedback_id,
            team_id=team_id,
            project_id=project_id,
            decision_id=decision_id,
            before=before,
            after=after,
            user_text=user_text,
            now=now,
        )
        return self._feedback.propose_candidates(
            feedback=fb, system_prompt=propose_system_prompt
        )

    def confirm_memory(self, memory_id: str) -> None:
        """USER_CONFIRMATION -> STORE_MEMORY：候选 -> active（规格 §4.2 第 4 步）。"""
        self._feedback.confirm_candidate(memory_id)

    def reject_memory(self, memory_id: str) -> None:
        """拒绝候选，归档保留审计（规格 §4.2 第 4 步）。"""
        self._feedback.reject_candidate(memory_id)


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #


def _split_judgments(
    memories: list[MemoryRule], judgments
) -> tuple[list[AppliedMemory], list[IgnoredMemory]]:
    """把适用性判断拆成 applied / ignored 两个可解释列表（规格 §4.3）。"""
    from schemas import ApplicabilityDecision

    mem_map = {m.id: m for m in memories}
    applied: list[AppliedMemory] = []
    ignored: list[IgnoredMemory] = []
    for j in judgments:
        rule = mem_map.get(j.memory_id)
        if rule is None:
            continue
        if j.decision == ApplicabilityDecision.apply:
            applied.append(
                AppliedMemory(
                    memory_id=rule.id,
                    rule_type=rule.rule_type.value,
                    trigger=rule.trigger,
                    instruction=rule.instruction,
                    reason=j.reason,
                )
            )
        else:
            ignored.append(
                IgnoredMemory(
                    memory_id=rule.id,
                    rule_type=rule.rule_type.value,
                    trigger=rule.trigger,
                    reason=j.reason,
                )
            )
    return applied, ignored
