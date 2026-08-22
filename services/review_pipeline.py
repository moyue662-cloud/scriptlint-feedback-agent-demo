"""模态无关的审片管线边界。

现在只有剧本文本适配器。未来的字幕、ASR、说话人识别、角色跟踪和视觉状态
提取器，都应输出 ReviewObservation，再复用同一套规则检索与冲突审计。
"""
from __future__ import annotations

from schemas.multimodal import (
    EvidenceLocator,
    ReviewAsset,
    ReviewEvidence,
    ReviewModality,
    ReviewObservation,
)
from schemas.scriptlint import ScriptFact


def script_facts_to_observations(
    facts: list[ScriptFact], *, asset: ReviewAsset
) -> list[ReviewObservation]:
    if asset.modality != ReviewModality.script_text:
        raise ValueError("script_facts_to_observations 只接受 script_text 资产")
    return [
        ReviewObservation(
            id=f"observation_{fact.id}",
            project_id=fact.project_id,
            episode=fact.episode,
            subject=fact.subject,
            action=fact.action,
            statement=fact.statement,
            object=fact.object,
            value=fact.value,
            confidence=1.0,
            evidence=ReviewEvidence(
                id=fact.evidence_id,
                asset_id=asset.id,
                modality=ReviewModality.script_text,
                excerpt=fact.evidence_excerpt,
                locator=EvidenceLocator(line_number=fact.line_number),
            ),
        )
        for fact in facts
    ]
