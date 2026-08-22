"""面向未来多模态审片的稳定证据契约。

黑客松 Demo 只实现 script_text 适配器。后续字幕、音频和视频模型只需产出
同样的 ReviewObservation，规则记忆与审计层不依赖具体模态。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ReviewModality(str, Enum):
    script_text = "script_text"
    subtitle = "subtitle"
    audio = "audio"
    video_frame = "video_frame"


class EvidenceLocator(BaseModel):
    line_number: int | None = Field(default=None, ge=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    frame_number: int | None = Field(default=None, ge=0)
    bbox_xywh: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def _valid_time_range(self) -> "EvidenceLocator":
        if self.start_ms is not None and self.end_ms is not None and self.start_ms > self.end_ms:
            raise ValueError("start_ms 不能大于 end_ms")
        return self


class ReviewAsset(BaseModel):
    id: str
    project_id: str
    version_id: str
    modality: ReviewModality
    display_name: str
    uri: str | None = None
    content_hash: str


class ReviewEvidence(BaseModel):
    id: str
    asset_id: str
    modality: ReviewModality
    excerpt: str
    locator: EvidenceLocator


class ReviewObservation(BaseModel):
    """任意模态提取器交给审计核心的统一最小事实。"""

    id: str
    project_id: str
    episode: int = Field(ge=1)
    subject: str
    action: str
    statement: str
    object: str | None = None
    value: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence: ReviewEvidence
