"""build_receipt 工具（规格 7.2）。

确定性，不调用模型。把决策对象 + 证据消息组装为前端展示结构，
按五类对象分桶（规格 4.1「按已决定、待确认、已否决、任务、冲突展示」）。
"""
from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from schemas import DecisionRecord, Message


class ReceiptCard(BaseModel):
    """单条决策凭证的前端展示结构（规格 5.1 / 4.1）。"""

    id: str
    type: str
    summary: str
    owner: str | None = None
    deadline: str | None = None
    status: str
    confidence: float
    reason: str | None = None
    evidence: list[dict] = Field(default_factory=list)


class ReceiptBundle(BaseModel):
    """一次分析的结果集合，按五类对象分桶（规格 4.1）。"""

    confirmed: list[ReceiptCard] = Field(default_factory=list)
    proposal: list[ReceiptCard] = Field(default_factory=list)
    rejected: list[ReceiptCard] = Field(default_factory=list)
    task: list[ReceiptCard] = Field(default_factory=list)
    conflict: list[ReceiptCard] = Field(default_factory=list)
    unknown: list[ReceiptCard] = Field(default_factory=list)


def build_receipt(
    *,
    decisions: Sequence[DecisionRecord],
    messages: Sequence[Message],
) -> ReceiptBundle:
    """决策对象 + 证据 -> 前端展示结构（规格 7.2）。"""
    msg_map = {m.id: m for m in messages}
    bundle = ReceiptBundle()

    for d in decisions:
        evidence: list[dict] = []
        for mid in d.evidence_message_ids:
            m = msg_map.get(mid)
            if m is not None:
                evidence.append(
                    {"message_id": m.id, "sender": m.sender, "content": m.content}
                )
            else:
                evidence.append(
                    {"message_id": mid, "sender": None, "content": None}
                )

        card = ReceiptCard(
            id=d.id,
            type=d.type.value,
            summary=d.summary,
            owner=d.owner,
            deadline=d.deadline.isoformat() if d.deadline else None,
            status=d.status.value,
            confidence=d.confidence,
            reason=d.reason,
            evidence=evidence,
        )

        bucket: list[ReceiptCard] | None = getattr(bundle, d.type.value, None)
        if bucket is not None:
            bucket.append(card)
        else:
            bundle.unknown.append(card)

    return bundle
