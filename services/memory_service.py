"""记忆服务：检索 / 注入 / 评分 / 作用域隔离。

对应规格 §6.3（检索与注入）、§6.4（冲突处理优先级）、§6.5（防止错误记忆）。

检索五步（规格 §6.3）：
  1. 硬过滤：team_id、项目范围、active 状态、规则类型
  2. 召回：关键词命中 + 简单相似度，最多 8 条候选
  3. 适用性判断：apply / ignore / conflict
  4. 重排：范围具体性、来源可靠性、置信度、最近有效反馈
  5. 注入：最多 5 条、目标不超过 300 tokens

作用域隔离（规格 §6.5）：默认禁止跨团队使用——硬过滤只查本团队。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Sequence

from config import AppConfig, CONFIG
from providers import LLMProvider
from repositories.sqlite import SQLiteRepository
from schemas import (
    ApplicabilityDecision,
    ApplicabilityJudgment,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    RuleType,
)


class MemoryService:
    """记忆检索与注入服务（规格 §6.3 / §6.5）。

    依赖 Repository（持久）与 Provider（适用性判断可选调模型）。
    P0 阶段适用性判断用确定性规则，不强制调模型（规格 §13.1 砍功能触发器）。
    """

    def __init__(
        self,
        repo: SQLiteRepository,
        *,
        config: AppConfig | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._repo = repo
        self._cfg = config or CONFIG
        self._provider = provider  # 可选，P0 适用性判断用确定性规则

    # -- 检索 ------------------------------------------------------------- #

    def retrieve(
        self,
        *,
        team_id: str,
        project_id: str,
        query: str,
        rule_types: list[RuleType] | None = None,
    ) -> list[MemoryRule]:
        """检索相关记忆（规格 §6.3 第 1-2 步）。

        硬过滤只查本团队（作用域隔离，规格 §6.5）；
        召回按关键词命中 + 简单相似度排序，取 top-k。
        """
        # 1. 硬过滤：team_id + active + 项目范围 + 规则类型
        candidates = self._repo.list_active_memories(
            team_id=team_id,
            project_id=project_id,
            rule_types=rule_types,
        )
        if not candidates:
            return []

        # 2. 召回：评分 + 取 top-k
        scored = [
            (self._score(rule, query, project_id), rule) for rule in candidates
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        topk = self._cfg.memory_recall_topk
        return [rule for _, rule in scored[:topk]]

    def _score(self, rule: MemoryRule, query: str, project_id: str) -> float:
        """评分公式（规格 §6.3 建议基线）。

        score = 0.40 * semantic_similarity
              + 0.25 * keyword_match
              + 0.20 * scope_specificity
              + 0.10 * confidence
              + 0.05 * recency
        """
        sem = _token_jaccard(rule.trigger, query)
        kw = _keyword_hit_ratio(rule.trigger, query)
        scope = 1.0 if (
            rule.scope == MemoryScope.project and rule.project_id == project_id
        ) else 0.5
        conf = rule.confidence
        recency = _recency_score(rule.last_used_at)
        return 0.40 * sem + 0.25 * kw + 0.20 * scope + 0.10 * conf + 0.05 * recency

    # -- 适用性判断 ------------------------------------------------------- #

    def judge_applicability(
        self,
        *,
        memories: Sequence[MemoryRule],
        query: str,
    ) -> list[ApplicabilityJudgment]:
        """对每条候选记忆输出 apply / ignore / conflict（规格 §6.3 第 3 步 / §9.3）。

        P0 用确定性规则（关键词命中 -> apply，否则 ignore）。
        冲突检测由 detect_conflicts 工具单独负责，此处不重复。
        """
        judgments: list[ApplicabilityJudgment] = []
        for rule in memories:
            if _keyword_hit_ratio(rule.trigger, query) > 0:
                judgments.append(
                    ApplicabilityJudgment(
                        memory_id=rule.id,
                        decision=ApplicabilityDecision.apply,
                        reason=f"查询命中触发条件「{rule.trigger}」",
                    )
                )
            else:
                judgments.append(
                    ApplicabilityJudgment(
                        memory_id=rule.id,
                        decision=ApplicabilityDecision.ignore,
                        reason="查询未命中触发条件",
                    )
                )
        return judgments

    # -- 注入 ------------------------------------------------------------- #

    def build_injection(
        self,
        *,
        memories: Sequence[MemoryRule],
        judgments: Sequence[ApplicabilityJudgment],
    ) -> list[MemoryRule]:
        """重排 + 限额注入（规格 §6.3 第 4-5 步）。

        只注入 apply 的记忆；按优先级（§6.4）与置信度重排；
        最多 memory_max_rules 条、目标不超过 memory_max_tokens。
        """
        apply_ids = {
            j.memory_id
            for j in judgments
            if j.decision == ApplicabilityDecision.apply
        }
        applicable = [m for m in memories if m.id in apply_ids]
        if not applicable:
            return []

        # 重排：硬约束 > 项目级 > 团队级，同级按置信度降序（规格 §6.4 优先级）
        applicable.sort(key=_priority_key, reverse=True)

        injected: list[MemoryRule] = []
        token_sum = 0
        for rule in applicable:
            if len(injected) >= self._cfg.memory_max_rules:
                break
            cost = _estimate_tokens(rule)
            if token_sum + cost > self._cfg.memory_max_tokens:
                continue  # 超预算则跳过该条，不强行截断
            injected.append(rule)
            token_sum += cost
        return injected

    # -- 反馈降权 --------------------------------------------------------- #

    def record_use(
        self,
        *,
        memory_id: str,
        positive: bool = False,
        negative: bool = False,
        used_at: datetime,
    ) -> None:
        """记录一次记忆使用与反馈（规格 §6.5 负反馈降权）。"""
        self._repo.record_memory_use(
            memory_id,
            positive=positive,
            negative=negative,
            used_at=used_at,
        )

    def activate(self, memory_id: str) -> None:
        """候选记忆 -> active（规格 §6.2 / ADR-005，需用户确认）。"""
        self._repo.update_memory_status(memory_id, MemoryStatus.active)

    def pause(self, memory_id: str) -> None:
        """暂停记忆，保留审计记录（规格 §6.5）。"""
        self._repo.update_memory_status(memory_id, MemoryStatus.paused)


# --------------------------------------------------------------------------- #
# 评分辅助
# --------------------------------------------------------------------------- #


def _token_jaccard(a: str, b: str) -> float:
    """CJK 字符集合的 Jaccard 相似度（简单语义近似）。"""
    sa = {c for c in a if "一" <= c <= "鿿"}
    sb = {c for c in b if "一" <= c <= "鿿"}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# 引号字符：ASCII 单/双引号 + 中文单/双引号（规格 §5.2 用 「」 风格）
_QUOTE_CHARS = "'\"‘’“”"
_QUOTE_RE = re.compile(f"[{_QUOTE_CHARS}]([^{_QUOTE_CHARS}]+)[{_QUOTE_CHARS}]")


def _extract_keywords(trigger: str) -> list[str]:
    """从触发条件提取关键词（规格 §5.2）。

    触发条件写作「句子包含'要不''可以试试'」，关键词是引号内的完整短语。
    无引号时把整个触发条件作为一个短语——绝不拆成单字，避免「不」「要」
    这类高频字在无关查询里误命中。
    """
    quoted = _QUOTE_RE.findall(trigger)
    if quoted:
        return [q.strip() for q in quoted if q.strip()]
    stripped = trigger.strip()
    return [stripped] if stripped else []


def _keyword_hit_ratio(trigger: str, query: str) -> float:
    """触发条件关键词在查询中的命中比例。"""
    keywords = _extract_keywords(trigger)
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if k in query)
    return hits / len(keywords)


def _recency_score(last_used_at: datetime | None) -> float:
    """最近使用度：从未用 -> 0，越近 -> 越接近 1。"""
    if last_used_at is None:
        return 0.0
    # 简化：用过的就给基础分，避免依赖系统时钟做衰减
    return 0.5


def _priority_key(rule: MemoryRule) -> tuple[int, float]:
    """重排优先级键（规格 §6.4）。

    硬约束(4) > 项目级角色/负面(3) > 团队级角色/负面(2) > 输出偏好(1)。
    """
    type_weight = {
        RuleType.hard_constraint: 4,
        RuleType.role: 3,
        RuleType.negative_decision: 3,
        RuleType.speech_act: 2,
        RuleType.output_preference: 1,
    }[rule.rule_type]
    scope_bonus = 1 if (
        rule.scope == MemoryScope.project and rule.project_id is not None
    ) else 0
    return (type_weight + scope_bonus, rule.confidence)


def _estimate_tokens(rule: MemoryRule) -> int:
    """粗略估算一条记忆注入占用的 token 数（中文 ~1.5 字/token）。"""
    text = f"{rule.trigger} {rule.instruction}"
    return max(1, math.ceil(len(text) / 1.5))
