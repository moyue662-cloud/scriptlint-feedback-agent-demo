"""面向未来多模态审片的稳定证据契约。

黑客松 Demo 只实现 script_text 适配器。后续字幕、音频和视频模型只需产出
同样的 ReviewObservation，规则记忆与审计层不依赖具体模态。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ReviewModality(str, Enum):
    script_text = "script_text"
    subtitle = "subtitle"
    audio = "audio"
    video = "video"
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


class TranscriptSegment(BaseModel):
    """ASR 输出的一段带时间码文本。"""

    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    speaker_tag: str | None = None
    speaker_role: str | None = None
    revised: bool = False

    @model_validator(mode="after")
    def _valid_segment_range(self) -> "TranscriptSegment":
        if self.start_ms > self.end_ms:
            raise ValueError("start_ms 不能大于 end_ms")
        return self


class ScriptDialogueLine(BaseModel):
    id: str
    line_number: int = Field(ge=1)
    speaker: str | None = None
    text: str


class IgnoredScriptLine(BaseModel):
    """含冒号但被判定为非台词的剧本行，供用户预检。"""

    line_number: int = Field(ge=1)
    text: str
    label: str | None = None
    reason: str


class ScriptDialogueParseResult(BaseModel):
    dialogues: list[ScriptDialogueLine]
    ignored_lines: list[IgnoredScriptLine]
    discovered_characters: list[str] = Field(default_factory=list)


class SubtitleObservation(BaseModel):
    """从成片画面硬字幕提取的一条带时间码文字证据。"""

    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    frame_number: int = Field(ge=0)
    text: str
    confidence: float = Field(ge=0, le=1)
    source: str = "ocr"

    @model_validator(mode="after")
    def _valid_subtitle_range(self) -> "SubtitleObservation":
        if self.start_ms > self.end_ms:
            raise ValueError("start_ms 不能大于 end_ms")
        return self


class DialogueMatchStatus(str, Enum):
    matched = "matched"
    changed = "changed"
    missing = "missing"
    extra = "extra"
    unverified = "unverified"


class DialogueAlignment(BaseModel):
    id: str
    status: DialogueMatchStatus
    script_line_number: int | None = Field(default=None, ge=1)
    speaker: str | None = None
    expected_text: str | None = None
    recognized_text: str | None = None
    subtitle_text: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    similarity: float = Field(default=0, ge=0, le=1)
    subtitle_start_ms: int | None = Field(default=None, ge=0)
    subtitle_end_ms: int | None = Field(default=None, ge=0)
    subtitle_similarity: float | None = Field(default=None, ge=0, le=1)
    phonetic_similarity: float | None = Field(default=None, ge=0, le=1)
    semantic_similarity: float | None = Field(default=None, ge=0, le=1)
    evidence_match_basis: str | None = None
    resolved_by_audio: bool = False
    resolved_by_subtitle: bool = False
    reason: str
    suggestion: str


class AudioQualityMetrics(BaseModel):
    duration_ms: int = Field(ge=0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float = Field(ge=0, le=1)
    silence_ratio: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class AudioReviewReport(BaseModel):
    """视频音轨相对剧本台词的可复核审计结果。"""

    source_name: str
    content_hash: str
    script_hash: str
    model_name: str
    detected_language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    transcript_segments: list[TranscriptSegment]
    script_dialogues: list[ScriptDialogueLine]
    ignored_script_lines: list[IgnoredScriptLine] = Field(default_factory=list)
    subtitle_observations: list[SubtitleObservation] = Field(default_factory=list)
    ocr_model_name: str | None = None
    ocr_frame_count: int = Field(default=0, ge=0)
    ocr_rescued_count: int = Field(default=0, ge=0)
    ocr_warnings: list[str] = Field(default_factory=list)
    subtitle_source_name: str | None = None
    manual_revision_count: int = Field(default=0, ge=0)
    speaker_mapping_count: int = Field(default=0, ge=0)
    alignments: list[DialogueAlignment]
    overall_similarity: float = Field(ge=0, le=1)
    matched_count: int = Field(ge=0)
    changed_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    extra_count: int = Field(ge=0)
    unverified_count: int = Field(default=0, ge=0)
    quality: AudioQualityMetrics
    elapsed_ms: float = Field(ge=0)
    created_at: datetime


class VisualIssueType(str, Enum):
    black_frame = "black_frame"
    blur = "blur"
    freeze = "freeze"


class VisualIssue(BaseModel):
    """画面基础质量候选，只描述可测量信号，不推断剧情语义。"""

    id: str
    issue_type: VisualIssueType
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    frame_number: int = Field(ge=0)
    score: float = Field(ge=0)
    description: str

    @model_validator(mode="after")
    def _valid_visual_range(self) -> "VisualIssue":
        if self.start_ms > self.end_ms:
            raise ValueError("start_ms 不能大于 end_ms")
        return self


class VisualQualityReport(BaseModel):
    """第一阶段非音频证据：镜头变化和画面基础质量。"""

    sample_interval_ms: int = Field(gt=0)
    sampled_frame_count: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    shot_change_count: int = Field(ge=0)
    black_frame_count: int = Field(ge=0)
    blur_frame_count: int = Field(ge=0)
    freeze_span_count: int = Field(ge=0)
    issues: list[VisualIssue] = Field(default_factory=list)
    elapsed_ms: float = Field(ge=0)
