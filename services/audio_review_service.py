"""视频音轨提取、中文 ASR 与剧本台词对齐。

这一层只审计声音证据，不推断画面、表情、动作或说话人身份。所有异常都保留
时间码和 ASR 原文，供编导回看后确认。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
import time
from typing import Protocol
import wave

import numpy as np

from schemas.multimodal import (
    AudioQualityMetrics,
    AudioReviewReport,
    DialogueAlignment,
    DialogueMatchStatus,
    IgnoredScriptLine,
    ScriptDialogueParseResult,
    ScriptDialogueLine,
    SubtitleObservation,
    TranscriptSegment,
)


MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 12 * 60
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
OCR_SAMPLE_INTERVAL_MS = 1500
MAX_OCR_FRAMES = 240

_NON_DIALOGUE_SECTIONS = {
    "作品信息",
    "项目信息",
    "基本信息",
    "人物设定",
    "角色设定",
    "人物介绍",
    "角色介绍",
    "创作说明",
    "剧本说明",
    "故事简介",
    "剧情梗概",
    "世界观",
    "背景介绍",
    "前言",
    "使用说明",
}
_CHARACTER_SECTIONS = {"人物设定", "角色设定", "人物介绍", "角色介绍"}
_CHARACTER_LIST_LABELS = {"核心人物", "主要人物", "登场人物", "角色列表", "人物"}
_NON_DIALOGUE_LABELS = {
    "类型",
    "题材",
    "原作",
    "改编",
    "剧名",
    "片名",
    "标题",
    "作品名",
    "动画结构",
    "当前编译时长",
    "当前画面规格",
    "核心人物",
    "主要人物",
    "登场人物",
    "角色列表",
    "核心主题",
    "核心反转",
    "时长",
    "画面规格",
    "分辨率",
    "集数",
    "版本",
    "场景",
    "地点",
    "时间",
    "镜头",
    "画面",
    "动作",
    "表情",
    "音效",
    "bgm",
    "sfx",
    "字幕",
    "道具",
    "服装",
    "备注",
    "说明",
    "制作说明",
    "导演说明",
    "镜头说明",
    "故事梗概",
    "剧情梗概",
    "背景介绍",
    "情景介绍",
    "场景介绍",
}
_VOICE_ROLES = {"旁白", "画外音", "内心独白", "系统音", "系统", "众人", "广播"}
_SEMANTIC_REPLACEMENTS = (
    ("没有办法", "无法"),
    ("没办法", "无法"),
    ("不可以", "不能"),
    ("不允许", "不能"),
    ("马上", "立即"),
    ("立刻", "立即"),
    ("这一个", "这个"),
    ("那一个", "那个"),
)
_CONTRAST_PAIRS = (
    ("左手", "右手"),
    ("左脸", "右脸"),
    ("之前", "之后"),
    ("里面", "外面"),
    ("进入", "出去"),
    ("买入", "卖出"),
    ("打开", "关上"),
    ("开启", "关闭"),
)


class AudioReviewError(RuntimeError):
    """可以安全展示给用户的音频审片错误。"""


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str | None = None
    language_probability: float | None = None


@dataclass(frozen=True)
class TextEquivalence:
    kind: str | None
    text_similarity: float
    phonetic_similarity: float
    semantic_similarity: float


class SpeechTranscriber(Protocol):
    model_name: str

    def transcribe(self, audio_path: str | Path) -> TranscriptionResult: ...


class SubtitleReader(Protocol):
    model_name: str

    def recognize(self, image: np.ndarray) -> list[tuple[str, float]]: ...


class FasterWhisperTranscriber:
    """延迟加载 faster-whisper；模型只在第一次真正审片时下载。"""

    def __init__(self, model_name: str = "tiny") -> None:
        self.model_name = model_name
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - 由部署依赖决定
            raise AudioReviewError(
                "语音识别组件未安装，请安装 requirements.txt 后重启应用。"
            ) from exc
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str | Path) -> TranscriptionResult:
        try:
            raw_segments, info = self._model.transcribe(
                str(audio_path),
                language="zh",
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            segments = [
                TranscriptSegment(
                    id=f"asr_{index:04d}",
                    start_ms=max(0, round(segment.start * 1000)),
                    end_ms=max(0, round(segment.end * 1000)),
                    text=segment.text.strip(),
                    confidence=_log_probability_to_confidence(
                        getattr(segment, "avg_logprob", None)
                    ),
                )
                for index, segment in enumerate(raw_segments, start=1)
                if segment.text.strip()
            ]
        except Exception as exc:  # pragma: no cover - 模型/媒体运行时错误
            raise AudioReviewError(f"语音转写失败：{exc}") from exc
        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
        )


class RapidOcrSubtitleReader:
    """轻量中文硬字幕 OCR；模型在第一次启用字幕增强时加载。"""

    model_name = "RapidOCR PP-OCRv6 small"

    def __init__(self, text_score: float = 0.5) -> None:
        try:
            from rapidocr import RapidOCR
            self._engine = RapidOCR()
        except Exception as exc:  # pragma: no cover - 由部署运行时决定
            raise AudioReviewError(
                "字幕 OCR 组件加载失败："
                f"{type(exc).__name__}: {exc}。"
                "请确认 Python 依赖与 Linux 图形运行库已安装后重启应用。"
            ) from exc
        self._text_score = text_score

    def recognize(self, image: np.ndarray) -> list[tuple[str, float]]:
        try:
            result = self._engine(image, text_score=self._text_score)
        except Exception as exc:  # pragma: no cover - 模型运行时错误
            raise AudioReviewError(f"字幕 OCR 识别失败：{exc}") from exc
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if texts is None or scores is None:
            return []
        return [
            (to_simplified_chinese(str(text).strip()), float(score))
            for text, score in zip(texts, scores)
            if str(text).strip()
        ]


def parse_script_dialogues(script_text: str) -> ScriptDialogueParseResult:
    """按 Markdown 章节和字段语义提取“角色：台词”，并保留排除依据。"""
    lines = script_text.splitlines()
    discovered_characters = _discover_characters(lines)
    dialogues: list[ScriptDialogueLine] = []
    ignored_lines: list[IgnoredScriptLine] = []
    current_section = ""
    pending_cue: tuple[int, str, str] | None = None

    def ignore_pending(reason: str) -> None:
        nonlocal pending_cue
        if pending_cue is None:
            return
        cue_line, cue_text, cue_speaker = pending_cue
        ignored_lines.append(
            IgnoredScriptLine(
                line_number=cue_line,
                text=cue_text,
                label=cue_speaker,
                reason=reason,
            )
        )
        pending_cue = None

    for line_number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        heading = _markdown_heading(stripped)
        if heading:
            ignore_pending("说话人提示后遇到新章节，没有找到台词正文")
            level, title = heading
            if level <= 2:
                current_section = title
            continue
        if not stripped:
            continue

        is_quote = stripped.startswith(">")
        candidate = re.sub(r"^(?:[-*+]\s+|>\s*)", "", stripped).strip()
        if _formatting_only(candidate):
            ignore_pending("说话人提示后只有排版符号，没有可审核的台词正文")
            continue

        match = re.match(r"^([^：:]{1,40})[：:]\s*(.*)$", candidate)
        if not match:
            if pending_cue is None:
                continue
            if is_quote or _standalone_stage_direction(candidate):
                ignore_pending("说话人提示后只有动作或说明，没有可审核的台词正文")
                continue
            text = _clean_markdown(candidate)
            if not normalize_dialogue(text):
                ignore_pending("说话人提示后的内容只有符号，没有可审核的语音文本")
                continue
            _, _, speaker = pending_cue
            dialogues.append(
                ScriptDialogueLine(
                    id=f"script_dialogue_{line_number}",
                    line_number=line_number,
                    speaker=speaker,
                    text=text,
                )
            )
            pending_cue = None
            continue

        ignore_pending("前一个说话人提示后直接出现了新的说话人，没有找到台词正文")
        raw_label = _clean_markdown(match.group(1))
        raw_text = match.group(2).strip()
        text = _clean_markdown(raw_text)
        speaker = re.sub(r"[（(][^）)]*[）)]", "", raw_label).strip()
        normalized_label = re.sub(r"\s+", "", speaker).lower()

        reason: str | None = None
        if is_quote:
            reason = "Markdown 引用/说明文字，不作为成片台词"
        elif _section_is_non_dialogue(current_section):
            reason = f"位于“{current_section}”说明章节，不作为成片台词"
        elif _is_non_dialogue_label(normalized_label):
            reason = f"“{speaker}”是作品元数据或制作字段，不是角色名"
        elif not _plausible_speaker(speaker, discovered_characters):
            reason = "冒号前内容不像角色名，按情景或背景说明排除"

        if reason:
            ignored_lines.append(
                IgnoredScriptLine(
                    line_number=line_number,
                    text=stripped,
                    label=speaker or None,
                    reason=reason,
                )
            )
            continue

        if not normalize_dialogue(text):
            if not raw_text or _markdown_closer_only(raw_text):
                pending_cue = (line_number, stripped, speaker)
            else:
                ignored_lines.append(
                    IgnoredScriptLine(
                        line_number=line_number,
                        text=stripped,
                        label=speaker,
                        reason="冒号后只有停顿或排版符号，不作为成片台词",
                    )
                )
            continue

        dialogues.append(
            ScriptDialogueLine(
                id=f"script_dialogue_{line_number}",
                line_number=line_number,
                speaker=speaker,
                text=text,
            )
        )

    ignore_pending("说话人提示位于剧本结尾，没有找到台词正文")

    return ScriptDialogueParseResult(
        dialogues=dialogues,
        ignored_lines=ignored_lines,
        discovered_characters=sorted(discovered_characters),
    )


def extract_script_dialogues(script_text: str) -> list[ScriptDialogueLine]:
    """兼容旧调用：只返回结构化解析结果中的台词。"""
    return parse_script_dialogues(script_text).dialogues


def _discover_characters(lines: list[str]) -> set[str]:
    characters: set[str] = set()
    current_section = ""
    for raw in lines:
        stripped = raw.strip()
        heading = _markdown_heading(stripped)
        if heading:
            level, title = heading
            if level <= 2:
                current_section = title
            elif level >= 3 and _section_matches(current_section, _CHARACTER_SECTIONS):
                name = _clean_markdown(title).strip()
                if _basic_speaker_shape(name):
                    characters.add(name)
            continue
        candidate = re.sub(r"^(?:[-*+]\s+|>\s*)", "", stripped).strip()
        match = re.match(r"^([^：:]{1,20})[：:]\s*(.+)$", candidate)
        if not match:
            continue
        label = re.sub(r"\s+", "", _clean_markdown(match.group(1)))
        if label not in _CHARACTER_LIST_LABELS:
            continue
        for name in re.split(r"[、,，/；;\s]+", match.group(2)):
            name = _clean_markdown(name).strip()
            if _basic_speaker_shape(name):
                characters.add(name)
    return characters


def _markdown_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), _clean_markdown(match.group(2)).strip()


def _clean_markdown(value: str) -> str:
    return re.sub(r"[*_`~]", "", value).strip()


def _formatting_only(value: str) -> bool:
    """Markdown 分隔符或强调符本身绝不能成为台词。"""
    return bool(value) and not normalize_dialogue(_clean_markdown(value))


def _markdown_closer_only(value: str) -> bool:
    return bool(re.fullmatch(r"[*_`~\s]+", value))


def _standalone_stage_direction(value: str) -> bool:
    value = _clean_markdown(value).strip()
    pairs = (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"))
    return any(value.startswith(left) and value.endswith(right) for left, right in pairs)


def _section_matches(section: str, options: set[str]) -> bool:
    compact = re.sub(r"[\s一二三四五六七八九十0-9、.．:：()（）]+", "", section)
    return any(option in compact for option in options)


def _section_is_non_dialogue(section: str) -> bool:
    return _section_matches(section, _NON_DIALOGUE_SECTIONS)


def _is_non_dialogue_label(label: str) -> bool:
    if label in _NON_DIALOGUE_LABELS:
        return True
    return any(
        label.startswith(prefix)
        for prefix in ("场景", "镜头", "画面", "时间", "地点", "备注", "说明")
    )


def _basic_speaker_shape(speaker: str) -> bool:
    if not speaker or len(speaker) > 12:
        return False
    if re.search(r"[，。！？；;/《》【】\[\]{}]", speaker):
        return False
    return not bool(re.search(r"\s{2,}", speaker))


def _plausible_speaker(speaker: str, discovered_characters: set[str]) -> bool:
    if not _basic_speaker_shape(speaker):
        return False
    if speaker in _VOICE_ROLES or speaker in discovered_characters:
        return True
    # 没有角色表的普通剧本仍可直接使用；句式化前缀则视为说明。
    if re.search(r"(介绍|背景|设定|说明|结构|主题|反转|规格|时长|画面|镜头)$", speaker):
        return False
    return True


def normalize_dialogue(text: str) -> str:
    """保留中英文、数字，消除标点和空白对齐噪声。"""
    simplified = to_simplified_chinese(text)
    return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", simplified)).lower()


@lru_cache(maxsize=1)
def _traditional_to_simplified_converter():
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    return OpenCC("t2s")


@lru_cache(maxsize=4096)
def to_simplified_chinese(text: str) -> str:
    """统一用户可见证据与比较文本为简体中文；缺依赖时保持原文。"""
    converter = _traditional_to_simplified_converter()
    return converter.convert(text) if converter is not None else text


@lru_cache(maxsize=4096)
def _phonetic_form(text: str) -> str:
    compact = normalize_dialogue(text)
    if not compact:
        return ""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return ""
    syllables = lazy_pinyin(
        compact,
        style=Style.TONE3,
        neutral_tone_with_five=True,
        strict=False,
        errors=lambda value: list(value),
    )
    return "|".join(syllables)


def _semantic_form(text: str) -> str:
    value = normalize_dialogue(text)
    for source, target in _SEMANTIC_REPLACEMENTS:
        value = value.replace(source, target)
    return value


def _semantic_guards_match(expected: str, actual: str) -> bool:
    left = _semantic_form(expected)
    right = _semantic_form(actual)
    if re.findall(r"\d+(?:\.\d+)?", left) != re.findall(r"\d+(?:\.\d+)?", right):
        return False
    negations = ("不", "没", "未", "无", "别", "莫", "禁止")
    if [item for item in negations if item in left] != [
        item for item in negations if item in right
    ]:
        return False
    for first, second in _CONTRAST_PAIRS:
        if (first in left and second in right) or (
            second in left and first in right
        ):
            return False
    return True


def assess_text_equivalence(expected: str, actual: str) -> TextEquivalence:
    """按简体字面、带声调拼音、受保护的轻量语义依次判定等价。"""
    text_similarity = _text_similarity(expected, actual)
    left_pinyin = _phonetic_form(expected)
    right_pinyin = _phonetic_form(actual)
    phonetic_similarity = (
        SequenceMatcher(None, left_pinyin, right_pinyin, autojunk=False).ratio()
        if left_pinyin and right_pinyin
        else 0.0
    )
    left_semantic = _semantic_form(expected)
    right_semantic = _semantic_form(actual)
    semantic_similarity = (
        SequenceMatcher(None, left_semantic, right_semantic, autojunk=False).ratio()
        if left_semantic and right_semantic
        else 0.0
    )
    kind: str | None = None
    if text_similarity >= 0.98:
        kind = "简体字面一致"
    elif (
        min(len(normalize_dialogue(expected)), len(normalize_dialogue(actual))) >= 3
        and phonetic_similarity >= 0.98
    ):
        kind = "读音一致"
    elif semantic_similarity >= 0.94 and _semantic_guards_match(expected, actual):
        kind = "轻量语义一致"
    return TextEquivalence(
        kind=kind,
        text_similarity=text_similarity,
        phonetic_similarity=phonetic_similarity,
        semantic_similarity=semantic_similarity,
    )


def extract_subtitle_observations(
    video_path: str | Path,
    reader: SubtitleReader,
    *,
    sample_interval_ms: int = OCR_SAMPLE_INTERVAL_MS,
    max_frames: int = MAX_OCR_FRAMES,
    target_timestamps_ms: list[int] | None = None,
) -> tuple[list[SubtitleObservation], int]:
    """顺序解码视频并抽取下半屏硬字幕，返回去重后的时间码文字证据。"""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - 由部署依赖决定
        raise AudioReviewError("视频解码组件未安装，无法提取画面字幕。") from exc

    video_path = Path(video_path)
    observations: list[SubtitleObservation] = []
    latest_by_text: dict[str, int] = {}
    sampled_frames = 0
    try:
        with av.open(str(video_path)) as container:
            if not container.streams.video:
                raise AudioReviewError("视频中没有检测到画面轨，无法提取字幕。")
            stream = container.streams.video[0]
            duration_ms = round(container.duration / 1000) if container.duration else 0
            adaptive_interval = max(
                sample_interval_ms,
                math.ceil(duration_ms / max_frames) if duration_ms else sample_interval_ms,
            )
            targets = _prepare_ocr_targets(target_timestamps_ms or [], max_frames)
            target_index = 0
            next_sample_ms = 0
            decoded_frame_number = 0
            for frame in container.decode(stream):
                decoded_frame_number += 1
                if frame.pts is None or frame.time_base is None:
                    continue
                timestamp_ms = max(0, round(float(frame.pts * frame.time_base) * 1000))
                if targets:
                    if target_index >= len(targets):
                        break
                    if timestamp_ms < targets[target_index]:
                        continue
                    target_index += 1
                elif timestamp_ms < next_sample_ms:
                    continue
                image = frame.to_ndarray(format="bgr24")
                if image.size == 0:
                    continue
                crop_top = max(0, int(image.shape[0] * 0.48))
                subtitle_region = image[crop_top:, :, :]
                recognized = reader.recognize(subtitle_region)
                sampled_frames += 1
                next_sample_ms = timestamp_ms + adaptive_interval

                candidates = recognized[:8]
                if len(candidates) > 1:
                    combined = "".join(text for text, _ in candidates)
                    combined_score = sum(score for _, score in candidates) / len(candidates)
                    candidates = [*candidates, (combined, combined_score)]
                for text, score in candidates:
                    normalized = normalize_dialogue(text)
                    if len(normalized) < 2 or not 0 <= score <= 1:
                        continue
                    previous_index = latest_by_text.get(normalized)
                    if previous_index is not None:
                        previous = observations[previous_index]
                        if timestamp_ms - previous.end_ms <= adaptive_interval * 1.5:
                            observations[previous_index] = previous.model_copy(
                                update={
                                    "end_ms": timestamp_ms + adaptive_interval,
                                    "confidence": max(previous.confidence, score),
                                }
                            )
                            continue
                    observations.append(
                        SubtitleObservation(
                            id=f"subtitle_{len(observations) + 1:04d}",
                            start_ms=timestamp_ms,
                            end_ms=timestamp_ms + adaptive_interval,
                            frame_number=decoded_frame_number,
                            text=text,
                            confidence=score,
                        )
                    )
                    latest_by_text[normalized] = len(observations) - 1
                if sampled_frames >= max_frames:
                    break
    except AudioReviewError:
        raise
    except Exception as exc:
        raise AudioReviewError(f"无法提取视频字幕：{exc}") from exc
    return observations, sampled_frames


def _prepare_ocr_targets(values: list[int], max_frames: int) -> list[int]:
    targets: list[int] = []
    for value in sorted({max(0, int(item)) for item in values}):
        if not targets or value - targets[-1] >= 450:
            targets.append(value)
    if len(targets) <= max_frames:
        return targets
    step = len(targets) / max_frames
    return [targets[min(len(targets) - 1, math.floor(index * step))] for index in range(max_frames)]


def fuse_subtitle_evidence(
    alignments: list[DialogueAlignment],
    observations: list[SubtitleObservation],
) -> tuple[list[DialogueAlignment], int]:
    """字幕与剧本或音频任一证据等价时消歧，但不掩盖真正的无声/漏录。"""
    if not observations:
        return alignments, 0
    fused: list[DialogueAlignment] = []
    used_observations: set[str] = set()
    rescued_count = 0
    for alignment in alignments:
        status_value = getattr(alignment.status, "value", alignment.status)
        if not alignment.expected_text or status_value == DialogueMatchStatus.extra.value:
            fused.append(alignment)
            continue
        candidates = _subtitle_candidates(alignment, observations)
        scored = []
        for item in candidates:
            if item.id in used_observations:
                continue
            script_equivalence = assess_text_equivalence(
                alignment.expected_text, item.text
            )
            audio_equivalence = assess_text_equivalence(
                alignment.recognized_text or "", item.text
            )
            evidence_score = max(
                script_equivalence.text_similarity,
                script_equivalence.phonetic_similarity,
                script_equivalence.semantic_similarity,
                audio_equivalence.text_similarity,
                audio_equivalence.phonetic_similarity,
                audio_equivalence.semantic_similarity,
            )
            scored.append(
                (evidence_score, script_equivalence, audio_equivalence, item)
            )
        if not scored:
            fused.append(alignment)
            continue
        evidence_score, script_equivalence, audio_equivalence, subtitle = max(
            scored, key=lambda pair: pair[0]
        )
        if (
            evidence_score < 0.35
            and script_equivalence.kind is None
            and audio_equivalence.kind is None
        ):
            fused.append(alignment)
            continue

        updates: dict[str, object] = {
            "subtitle_text": subtitle.text,
            "subtitle_start_ms": subtitle.start_ms,
            "subtitle_end_ms": subtitle.end_ms,
            "subtitle_similarity": script_equivalence.text_similarity,
        }
        if (
            status_value == DialogueMatchStatus.changed.value
            and (script_equivalence.kind or audio_equivalence.kind)
        ):
            if script_equivalence.kind:
                basis = f"画面字幕与剧本{script_equivalence.kind}"
            else:
                basis = f"音频与画面字幕{audio_equivalence.kind}"
            updates.update(
                {
                    "status": DialogueMatchStatus.matched,
                    "resolved_by_subtitle": True,
                    "evidence_match_basis": basis,
                    "reason": f"{basis}；三方证据表明差异更可能来自繁简体、同音字或 ASR 误识别",
                    "suggestion": "系统已判定一致；关键台词仍可按时间码抽听确认",
                }
            )
            rescued_count += 1
            used_observations.add(subtitle.id)
        elif (
            status_value == DialogueMatchStatus.missing.value
            and script_equivalence.kind
        ):
            updates.update(
                {
                    "reason": "画面字幕与剧本一致，但音频中未稳定识别到该句；字幕不能证明实际收音完整",
                    "suggestion": "回听字幕对应时间码，区分漏录、音量过低与 ASR 未识别",
                }
            )
        elif status_value == DialogueMatchStatus.changed.value:
            updates.update(
                {
                    "reason": "音频与画面字幕都未能充分确认剧本原句，仍需人工复核",
                    "suggestion": "同时回看字幕时间码和音频时间码，确认是现场改词、字幕错误还是识别误差",
                }
            )
        fused.append(alignment.model_copy(update=updates))
    # OCR 可能在“疑似加词”生成之后才把同时间段的剧本行纠正为一致；
    # 此时移除重复的未匹配语音，避免同一句同时显示“正确”和“加词”。
    matched_windows = [
        (item.start_ms, item.end_ms)
        for item in fused
        if getattr(item.status, "value", item.status)
        == DialogueMatchStatus.matched.value
        and item.start_ms is not None
        and item.end_ms is not None
    ]
    deduplicated = [
        item
        for item in fused
        if not (
            getattr(item.status, "value", item.status)
            == DialogueMatchStatus.extra.value
            and item.start_ms is not None
            and item.end_ms is not None
            and any(
                _time_overlap_ratio(
                    item.start_ms, item.end_ms, matched_start, matched_end
                )
                >= 0.45
                for matched_start, matched_end in matched_windows
            )
        )
    ]
    return deduplicated, rescued_count


def _subtitle_candidates(
    alignment: DialogueAlignment,
    observations: list[SubtitleObservation],
) -> list[SubtitleObservation]:
    if alignment.start_ms is None:
        return observations
    end_ms = alignment.end_ms if alignment.end_ms is not None else alignment.start_ms
    nearby = [
        item
        for item in observations
        if item.end_ms >= alignment.start_ms - 2500 and item.start_ms <= end_ms + 2500
    ]
    return nearby or observations


def _text_similarity(expected: str, actual: str) -> float:
    left = normalize_dialogue(expected)
    right = normalize_dialogue(actual)
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
    if left in right or right in left:
        ratio = max(ratio, min(len(left), len(right)) / max(len(left), len(right)))
    return min(1.0, ratio)


def align_dialogues(
    script_dialogues: list[ScriptDialogueLine],
    transcript_segments: list[TranscriptSegment],
) -> tuple[list[DialogueAlignment], float]:
    """用全局字符序列对齐，避免 ASR 分段与剧本台词行不一致造成误报。"""
    expected_parts = [normalize_dialogue(row.text) for row in script_dialogues]
    actual_parts = [normalize_dialogue(row.text) for row in transcript_segments]
    expected = "".join(expected_parts)
    actual = "".join(actual_parts)
    if not expected:
        raise AudioReviewError("剧本中没有识别到“角色：台词”格式，请先补充台词头。")
    if not actual:
        return _all_missing(script_dialogues), 0.0

    matcher = SequenceMatcher(None, expected, actual, autojunk=False)
    matching_blocks = [block for block in matcher.get_matching_blocks() if block.size]
    script_ranges = _ranges(expected_parts)
    transcript_ranges = _ranges(actual_parts)
    matched_actual_positions: set[int] = set()
    alignments: list[DialogueAlignment] = []

    for row, (left, right) in zip(script_dialogues, script_ranges):
        expected_length = max(1, right - left)
        overlap_blocks: list[tuple[int, int, int]] = []
        for block in matching_blocks:
            overlap_left = max(left, block.a)
            overlap_right = min(right, block.a + block.size)
            if overlap_left >= overlap_right:
                continue
            actual_left = block.b + (overlap_left - block.a)
            size = overlap_right - overlap_left
            overlap_blocks.append((overlap_left, actual_left, size))
            matched_actual_positions.update(range(actual_left, actual_left + size))

        matched_chars = sum(size for _, _, size in overlap_blocks)
        coverage = matched_chars / expected_length
        actual_indexes = [
            position
            for _, actual_left, size in overlap_blocks
            for position in range(actual_left, actual_left + size)
        ]
        start_ms, end_ms, recognized = _actual_evidence(
            actual, actual_indexes, transcript_segments, transcript_ranges
        )
        equivalence = assess_text_equivalence(row.text, recognized) if recognized else None
        if coverage >= 0.98:
            status = DialogueMatchStatus.matched
            reason = "成片语音与剧本台词基本一致"
            suggestion = "无需修改；仍建议抽听时间码确认 ASR 没有误识别"
            evidence_match_basis = "字符对齐一致"
            resolved_by_audio = False
        elif equivalence is not None and equivalence.kind:
            status = DialogueMatchStatus.matched
            reason = f"音频证据与剧本{equivalence.kind}，判定成片台词一致"
            suggestion = "无需修改；关键台词仍建议按时间码抽听确认"
            evidence_match_basis = f"音频与剧本{equivalence.kind}"
            resolved_by_audio = True
            if actual_indexes:
                matched_actual_positions.update(
                    range(min(actual_indexes), max(actual_indexes) + 1)
                )
        elif coverage >= 0.42:
            status = DialogueMatchStatus.changed
            reason = "成片语音只匹配到部分剧本台词，可能存在错词、改词或 ASR 误识别"
            suggestion = "回看对应时间码，确认后补录台词或将现场改词更新进剧本版本"
            evidence_match_basis = None
            resolved_by_audio = False
        else:
            status = DialogueMatchStatus.missing
            reason = "未在成片语音中稳定找到这句剧本台词"
            suggestion = "检查是否漏拍、漏录、被剪掉，或 ASR 因噪声未识别"
            evidence_match_basis = None
            resolved_by_audio = False
        alignments.append(
            DialogueAlignment(
                id=f"alignment_{row.id}",
                status=status,
                script_line_number=row.line_number,
                speaker=row.speaker,
                expected_text=row.text,
                recognized_text=recognized or None,
                start_ms=start_ms,
                end_ms=end_ms,
                similarity=min(1.0, coverage),
                phonetic_similarity=(
                    None if equivalence is None else equivalence.phonetic_similarity
                ),
                semantic_similarity=(
                    None if equivalence is None else equivalence.semantic_similarity
                ),
                evidence_match_basis=evidence_match_basis,
                resolved_by_audio=resolved_by_audio,
                reason=reason,
                suggestion=suggestion,
            )
        )

    # 当整句几乎全是同音字时，字符匹配可能找不到范围；再做一次段级读音/语义兜底。
    claimed_fallback_segments: set[int] = set()
    for alignment_index, alignment in enumerate(alignments):
        if (
            getattr(alignment.status, "value", alignment.status)
            == DialogueMatchStatus.matched.value
            or not alignment.expected_text
        ):
            continue
        candidates: list[tuple[int, float, int, TranscriptSegment, TextEquivalence]] = []
        for segment_index, segment in enumerate(transcript_segments):
            if segment_index in claimed_fallback_segments:
                continue
            equivalence = assess_text_equivalence(alignment.expected_text, segment.text)
            if not equivalence.kind:
                continue
            rank = {
                "简体字面一致": 3,
                "读音一致": 2,
                "轻量语义一致": 1,
            }[equivalence.kind]
            candidates.append(
                (
                    rank,
                    max(
                        equivalence.text_similarity,
                        equivalence.phonetic_similarity,
                        equivalence.semantic_similarity,
                    ),
                    segment_index,
                    segment,
                    equivalence,
                )
            )
        if not candidates:
            continue
        _, _, segment_index, segment, equivalence = max(
            candidates, key=lambda item: (item[0], item[1])
        )
        segment_left, segment_right = transcript_ranges[segment_index]
        matched_actual_positions.update(range(segment_left, segment_right))
        claimed_fallback_segments.add(segment_index)
        alignments[alignment_index] = alignment.model_copy(
            update={
                "status": DialogueMatchStatus.matched,
                "recognized_text": to_simplified_chinese(segment.text),
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "phonetic_similarity": equivalence.phonetic_similarity,
                "semantic_similarity": equivalence.semantic_similarity,
                "evidence_match_basis": f"音频与剧本{equivalence.kind}",
                "resolved_by_audio": True,
                "reason": f"音频证据与剧本{equivalence.kind}，判定成片台词一致",
                "suggestion": "无需修改；关键台词仍建议按时间码抽听确认",
            }
        )

    matched_windows = [
        (item.start_ms, item.end_ms)
        for item in alignments
        if getattr(item.status, "value", item.status)
        == DialogueMatchStatus.matched.value
        and item.start_ms is not None
        and item.end_ms is not None
    ]

    # 如果某个有意义的 ASR 片段没有参与任何匹配，将它作为低优先级未匹配语音。
    for segment, (left, right) in zip(transcript_segments, transcript_ranges):
        segment_length = right - left
        if segment_length < 2:
            continue
        if any(
            _time_overlap_ratio(
                segment.start_ms, segment.end_ms, matched_start, matched_end
            )
            >= 0.45
            for matched_start, matched_end in matched_windows
        ):
            continue
        matched = sum(position in matched_actual_positions for position in range(left, right))
        if matched / segment_length >= 0.45:
            continue
        alignments.append(
            DialogueAlignment(
                id=f"alignment_extra_{segment.id}",
                status=DialogueMatchStatus.extra,
                recognized_text=to_simplified_chinese(segment.text),
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                similarity=matched / segment_length,
                reason="这段成片语音暂未稳定对应到剧本行；它不是剧本中的破折号，也不直接计为剧本错误",
                suggestion="仅在需要核对临场发挥或环境人声时回听；确认无关可忽略",
            )
        )

    return alignments, matcher.ratio()


def _time_overlap_ratio(
    start_ms: int,
    end_ms: int,
    reference_start_ms: int,
    reference_end_ms: int,
) -> float:
    duration = max(1, end_ms - start_ms)
    overlap = max(
        0,
        min(end_ms, reference_end_ms) - max(start_ms, reference_start_ms),
    )
    return overlap / duration


def extract_audio_track(video_path: str | Path, wav_path: str | Path) -> AudioQualityMetrics:
    """用 PyAV 解码视频音轨并输出 16kHz 单声道 WAV。"""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - 由部署依赖决定
        raise AudioReviewError("视频解码组件未安装，请安装 requirements.txt 后重启应用。") from exc

    video_path = Path(video_path)
    if video_path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise AudioReviewError("不支持该视频格式，请上传 MP4、MOV、MKV、WebM、AVI 或 M4V。")
    if video_path.stat().st_size > MAX_VIDEO_BYTES:
        raise AudioReviewError("视频超过 200MB。Demo 请截取需要审核的 1–10 分钟片段。")

    samples: list[np.ndarray] = []
    try:
        with av.open(str(video_path)) as container:
            if not container.streams.audio:
                raise AudioReviewError("视频中没有检测到音轨。")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            with wave.open(str(wav_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                for frame in container.decode(stream):
                    converted = resampler.resample(frame)
                    if converted is None:
                        continue
                    for audio_frame in converted if isinstance(converted, list) else [converted]:
                        chunk = np.asarray(audio_frame.to_ndarray()).reshape(-1).astype(np.int16)
                        if chunk.size:
                            output.writeframes(chunk.tobytes())
                            samples.append(chunk)
                flushed = resampler.resample(None)
                for audio_frame in flushed if isinstance(flushed, list) else ([flushed] if flushed else []):
                    chunk = np.asarray(audio_frame.to_ndarray()).reshape(-1).astype(np.int16)
                    if chunk.size:
                        output.writeframes(chunk.tobytes())
                        samples.append(chunk)
    except AudioReviewError:
        raise
    except Exception as exc:
        raise AudioReviewError(f"无法读取视频音轨：{exc}") from exc

    if not samples:
        raise AudioReviewError("音轨为空，无法执行语音审核。")
    all_samples = np.concatenate(samples).astype(np.float32)
    duration_seconds = all_samples.size / 16000
    if duration_seconds > MAX_AUDIO_DURATION_SECONDS:
        raise AudioReviewError("音轨超过 12 分钟。Demo 请先截取单集或关键片段。")
    return _quality_metrics(all_samples, duration_seconds)


class AudioReviewService:
    def __init__(
        self,
        transcriber: SpeechTranscriber,
        subtitle_reader: SubtitleReader | None = None,
    ) -> None:
        self._transcriber = transcriber
        self._subtitle_reader = subtitle_reader

    def review_video(
        self,
        *,
        video_path: str | Path,
        wav_path: str | Path,
        script_text: str,
        source_name: str,
        created_at: datetime | None = None,
    ) -> AudioReviewReport:
        started = time.perf_counter()
        quality = extract_audio_track(video_path, wav_path)
        transcription = self._transcriber.transcribe(wav_path)
        transcript_segments = [
            TranscriptSegment.model_validate(_model_payload(item)).model_copy(
                update={
                    "text": to_simplified_chinese(
                        str(_model_payload(item).get("text", ""))
                    )
                }
            )
            for item in transcription.segments
        ]
        parse_result = parse_script_dialogues(script_text)
        script_dialogues = parse_result.dialogues
        alignments, overall_similarity = align_dialogues(
            script_dialogues, transcript_segments
        )
        subtitle_observations: list[SubtitleObservation] = []
        ocr_frame_count = 0
        ocr_rescued_count = 0
        ocr_warnings: list[str] = []
        if self._subtitle_reader is not None:
            try:
                subtitle_observations, ocr_frame_count = extract_subtitle_observations(
                    video_path,
                    self._subtitle_reader,
                    target_timestamps_ms=[
                        (item.start_ms + item.end_ms) // 2
                        for item in transcript_segments
                    ],
                )
                alignments, ocr_rescued_count = fuse_subtitle_evidence(
                    alignments, subtitle_observations
                )
            except AudioReviewError as exc:
                ocr_warnings.append(str(exc))
        counts = {
            status: sum(item.status == status for item in alignments)
            for status in DialogueMatchStatus
        }
        digest = _sha256_file(video_path)
        return AudioReviewReport(
            source_name=source_name,
            content_hash=digest,
            script_hash=hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
            model_name=self._transcriber.model_name,
            detected_language=transcription.language,
            language_probability=transcription.language_probability,
            # Streamlit 热更新可能让缓存的 ASR 仍返回旧模块中的 Pydantic
            # 实例。字段完全相同但类身份不同，Pydantic v2 会逐条拒绝。
            # 在报告契约边界统一降为普通字典，重新按当前 schema 校验。
            transcript_segments=[_model_payload(item) for item in transcript_segments],
            script_dialogues=[_model_payload(item) for item in script_dialogues],
            ignored_script_lines=[
                _model_payload(item) for item in parse_result.ignored_lines
            ],
            subtitle_observations=[
                _model_payload(item) for item in subtitle_observations
            ],
            ocr_model_name=(
                self._subtitle_reader.model_name
                if self._subtitle_reader is not None
                else None
            ),
            ocr_frame_count=ocr_frame_count,
            ocr_rescued_count=ocr_rescued_count,
            ocr_warnings=ocr_warnings,
            alignments=[_model_payload(item) for item in alignments],
            overall_similarity=overall_similarity,
            matched_count=counts[DialogueMatchStatus.matched],
            changed_count=counts[DialogueMatchStatus.changed],
            missing_count=counts[DialogueMatchStatus.missing],
            extra_count=counts[DialogueMatchStatus.extra],
            quality=_model_payload(quality),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            created_at=created_at or datetime.now(timezone.utc),
        )


def _model_payload(value: object) -> object:
    """跨热更新模块边界传递稳定数据，不依赖 Pydantic 类对象身份。"""
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="python")
    return value


def _ranges(parts: list[str]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = 0
    for part in parts:
        result.append((cursor, cursor + len(part)))
        cursor += len(part)
    return result


def _actual_evidence(
    actual: str,
    indexes: list[int],
    segments: list[TranscriptSegment],
    ranges: list[tuple[int, int]],
) -> tuple[int | None, int | None, str]:
    if not indexes:
        return None, None, ""
    left, right = min(indexes), max(indexes) + 1
    selected = [
        segment
        for segment, (segment_left, segment_right) in zip(segments, ranges)
        if max(left, segment_left) < min(right, segment_right)
    ]
    if not selected:
        return None, None, actual[left:right]
    return (
        selected[0].start_ms,
        selected[-1].end_ms,
        to_simplified_chinese("".join(item.text for item in selected)),
    )


def _all_missing(script_dialogues: list[ScriptDialogueLine]) -> list[DialogueAlignment]:
    return [
        DialogueAlignment(
            id=f"alignment_{row.id}",
            status=DialogueMatchStatus.missing,
            script_line_number=row.line_number,
            speaker=row.speaker,
            expected_text=row.text,
            reason="音轨没有产生可用的语音转写，无法找到剧本台词",
            suggestion="检查视频是否静音、音量过低或语音识别组件是否支持当前语言",
        )
        for row in script_dialogues
    ]


def _quality_metrics(samples: np.ndarray, duration_seconds: float) -> AudioQualityMetrics:
    normalized = np.abs(samples) / 32768.0
    rms = float(np.sqrt(np.mean(np.square(samples / 32768.0))))
    peak = float(np.max(normalized))
    rms_dbfs = 20 * math.log10(max(rms, 1e-8))
    peak_dbfs = 20 * math.log10(max(peak, 1e-8))
    clipping_ratio = float(np.mean(normalized >= 0.99))
    silence_ratio = float(np.mean(normalized <= 0.009))
    warnings: list[str] = []
    if rms_dbfs < -35:
        warnings.append("整体音量偏低，ASR 可能漏词；建议检查收音或提高人声增益")
    if clipping_ratio > 0.01:
        warnings.append("疑似存在削波/爆音；建议回听高音量片段")
    if silence_ratio > 0.70:
        warnings.append("静音比例较高；若非剧情需要，请检查音轨是否缺失")
    return AudioQualityMetrics(
        duration_ms=round(duration_seconds * 1000),
        sample_rate=16000,
        channels=1,
        rms_dbfs=round(rms_dbfs, 2),
        peak_dbfs=round(peak_dbfs, 2),
        clipping_ratio=round(clipping_ratio, 6),
        silence_ratio=round(silence_ratio, 6),
        warnings=warnings,
    )


def _log_probability_to_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(1.0, math.exp(value))), 4)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
