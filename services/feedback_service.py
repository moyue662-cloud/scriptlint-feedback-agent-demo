"""反馈服务：用户纠正 -> 候选记忆。

对应规格 §4.2（纠正与记忆）、§6.2（写入原则）。

闭环（规格 §4.2）：
  1. 用户把「已决定」改为「只是提议」。
  2. 系统比较修改前后，生成候选规则。
  3. 用户查看规则适用范围、来源和示例，选择确认、编辑或拒绝。
  4. 被确认的规则进入 active 状态；被拒绝的候选只记为一次反馈事件，
     不进入生成提示词。

写入原则（规格 §6.2 / ADR-005）：
  - 模型提出的是 candidate，不得直接变成 active。
  - 候选记忆未经确认不会影响下一次运行（规格 §11.1）。
  - 每条记忆必须有适用范围、来源、置信度和撤销入口。
"""
from __future__ import annotations

from datetime import datetime

from providers import LLMProvider
from repositories.sqlite import SQLiteRepository
from schemas import (
    DecisionRecord,
    FeedbackEvent,
    MemoryCandidate,
    MemoryRule,
    MemoryStatus,
)
from tools.propose_memory import propose_memory


class FeedbackService:
    """纠正 -> 候选记忆服务（规格 §4.2 / §6.2）。

    依赖 Repository（持久）与 Provider（调用模型提取规则）。
    候选记忆落库时状态固定为 candidate，确认前不得被检索应用。
    """

    def __init__(self, repo: SQLiteRepository, *, provider: LLMProvider) -> None:
        self._repo = repo
        self._provider = provider

    # -- 记录纠正 --------------------------------------------------------- #

    def record_correction(
        self,
        *,
        feedback_id: str,
        team_id: str,
        project_id: str,
        decision_id: str | None,
        before: DecisionRecord,
        after: DecisionRecord,
        user_text: str | None = None,
        now: datetime,
    ) -> FeedbackEvent:
        """保存一次用户纠正（规格 §4.2 第 1 步 / §5.3 feedback_events）。

        before / after 序列化为 JSON 快照，供审计与候选记忆提取。
        """
        fb = FeedbackEvent(
            id=feedback_id,
            team_id=team_id,
            project_id=project_id,
            decision_id=decision_id,
            before_json=before.model_dump_json(),
            after_json=after.model_dump_json(),
            user_text=user_text,
            created_at=now,
        )
        self._repo.insert_feedback_event(fb)
        return fb

    # -- 提取候选记忆 ----------------------------------------------------- #

    def propose_candidates(
        self,
        *,
        feedback: FeedbackEvent,
        system_prompt: str = "",
    ) -> list[MemoryRule]:
        """从纠正中提取候选记忆（规格 §4.2 第 2 步 / §7.2 propose_memory）。

        模型只负责提取规则语义；落库时状态固定为 candidate，
        未经用户确认不会被检索应用（规格 §6.2 / §11.1）。
        """
        candidates = propose_memory(
            feedback=feedback,
            provider=self._provider,
            system_prompt=system_prompt,
        )
        rules: list[MemoryRule] = []
        for c in candidates:
            rule = _candidate_to_rule(c, created_at=feedback.created_at)
            # Provider 的局部序号（如 cand_000）只在一次调用内稳定；真实用户
            # 可能连续纠正多条凭证，不能让下一次反馈用 INSERT OR REPLACE
            # 覆盖上一条候选记忆。第一次仍保留简洁 ID，后续自动加反馈 ID。
            if self._repo.get_memory_rule(rule.id) is not None:
                rule = rule.model_copy(update={"id": f"{rule.id}_{feedback.id}"})
            self._repo.insert_memory_rule(rule)
            rules.append(rule)
        return rules

    # -- 确认 / 拒绝 ------------------------------------------------------ #

    def confirm_candidate(self, memory_id: str) -> None:
        """候选 -> active（规格 §4.2 第 4 步 / §6.2 / ADR-005）。

        必须由用户确认；确认后才会在后续运行中被检索应用。
        """
        self._repo.update_memory_status(memory_id, MemoryStatus.active)

    def reject_candidate(self, memory_id: str) -> None:
        """拒绝候选（规格 §4.2 第 4 步）。

        被拒绝的候选归档保留审计记录，不进入 active、不进入生成提示词。
        """
        self._repo.update_memory_status(memory_id, MemoryStatus.archived)

    def list_candidates(self, *, team_id: str, project_id: str) -> list[MemoryRule]:
        """查看待确认的候选记忆（规格 §4.2 第 3 步）。

        只列 candidate 状态，供用户查看适用范围、来源和示例。
        作用域隔离由 repo 保证：只查本团队，且同时含团队级与项目级规则。
        """
        return self._repo.list_memories_by_status(
            team_id=team_id,
            status=MemoryStatus.candidate,
            project_id=project_id,
        )


# --------------------------------------------------------------------------- #
# 转换辅助
# --------------------------------------------------------------------------- #


def _candidate_to_rule(c: MemoryCandidate, *, created_at: datetime) -> MemoryRule:
    """MemoryCandidate -> MemoryRule(status=candidate)。

    候选记忆状态固定为 candidate，确认后才转为 active（规格 §6.2）。
    """
    return MemoryRule(
        id=c.id,
        team_id=c.team_id,
        project_id=c.project_id,
        rule_type=c.rule_type,
        trigger=c.trigger,
        instruction=c.instruction,
        scope=c.scope,
        source_feedback_id=c.feedback_id,
        source_excerpt=c.source_excerpt,
        confidence=c.confidence,
        status=MemoryStatus.candidate,
        created_at=created_at,
    )
