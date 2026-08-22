"""detect_conflicts 工具（规格 7.2）。

混合：确定性规则检测明显冲突与取代关系。
P0 阶段不强制调用模型，用关键词重叠做近似；语义冲突留待 P1。
"""
from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from schemas import DecisionRecord, DecisionType


class ConflictItem(BaseModel):
    """一条冲突或取代关系。"""

    decision_id: str
    conflict_type: str  # supersede | duplicate | contradiction
    related_id: str | None = None
    reason: str


class ConflictReport(BaseModel):
    """detect_conflicts 输出。"""

    items: list[ConflictItem] = Field(default_factory=list)


def detect_conflicts(
    *,
    new_decisions: Sequence[DecisionRecord],
    history: Sequence[DecisionRecord] | None = None,
) -> ConflictReport:
    """检测冲突与取代关系（规格 7.2 / 6.4）。

    确定性规则：
    1. supersedes_id 非空 -> supersede 关系。
    2. 新决定与历史决定同主题：
       - rejected vs confirmed/proposal -> contradiction
       - 两条 confirmed -> duplicate
    3. 新决定之间同主题且结论相反 -> contradiction。
    """
    items: list[ConflictItem] = []
    all_new = list(new_decisions)
    history = list(history or [])

    # 1. 取代关系
    for d in all_new:
        if d.supersedes_id:
            items.append(
                ConflictItem(
                    decision_id=d.id,
                    conflict_type="supersede",
                    related_id=d.supersedes_id,
                    reason=f"{d.id} 取代了 {d.supersedes_id}",
                )
            )

    # 2. 与历史决定的重复 / 矛盾
    for d in all_new:
        for h in history:
            if not _same_topic(d, h):
                continue
            if d.type == DecisionType.rejected and h.type in {
                DecisionType.confirmed,
                DecisionType.proposal,
            }:
                items.append(
                    ConflictItem(
                        decision_id=d.id,
                        conflict_type="contradiction",
                        related_id=h.id,
                        reason=f"新决定否决了历史 {h.id} 的同类方案",
                    )
                )
            elif d.type == h.type == DecisionType.confirmed:
                items.append(
                    ConflictItem(
                        decision_id=d.id,
                        conflict_type="duplicate",
                        related_id=h.id,
                        reason=f"与历史 {h.id} 重复确认",
                    )
                )

    # 3. 新决定之间的矛盾
    for i, a in enumerate(all_new):
        for b in all_new[i + 1 :]:
            if not _same_topic(a, b):
                continue
            if {a.type, b.type} == {DecisionType.rejected, DecisionType.confirmed}:
                items.append(
                    ConflictItem(
                        decision_id=a.id,
                        conflict_type="contradiction",
                        related_id=b.id,
                        reason=f"{a.id} 与 {b.id} 结论矛盾",
                    )
                )

    return ConflictReport(items=items)


def _same_topic(a: DecisionRecord, b: DecisionRecord) -> bool:
    """判断两条决定是否讨论同一主题：CJK 字符集合的 Jaccard 重叠 >= 0.5。"""
    sa = {c for c in a.summary if "一" <= c <= "鿿"}
    sb = {c for c in b.summary if "一" <= c <= "鿿"}
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= 0.5
