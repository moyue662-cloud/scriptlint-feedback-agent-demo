"""视频音轨提取、中文 ASR 与剧本台词对齐。

这一层只审计声音证据，不推断画面、表情、动作或说话人身份。所有异常都保留
时间码和 ASR 原文，供编导回看后确认。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
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
    TranscriptSegment,
)


MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 12 * 60
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

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


class AudioReviewError(RuntimeError):
    """可以安全展示给用户的音频审片错误。"""


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str | None = None
    language_probability: float | None = None


class SpeechTranscriber(Protocol):
    model_name: str

    def transcribe(self, audio_path: str | Path) -> TranscriptionResult: ...


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


def parse_script_dialogues(script_text: str) -> ScriptDialogueParseResult:
    """按 Markdown 章节和字段语义提取“角色：台词”，并保留排除依据。"""
    lines = script_text.splitlines()
    discovered_characters = _discover_characters(lines)
    dialogues: list[ScriptDialogueLine] = []
    ignored_lines: list[IgnoredScriptLine] = []
    current_section = ""

    for line_number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        heading = _markdown_heading(stripped)
        if heading:
            level, title = heading
            if level <= 2:
                current_section = title
            continue
        if not stripped:
            continue

        is_quote = stripped.startswith(">")
        candidate = re.sub(r"^(?:[-*+]\s+|>\s*)", "", stripped).strip()
        match = re.match(r"^([^：:]{1,40})[：:]\s*(.+)$", candidate)
        if not match:
            continue

        raw_label = _clean_markdown(match.group(1))
        text = match.group(2).strip()
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

        dialogues.append(
            ScriptDialogueLine(
                id=f"script_dialogue_{line_number}",
                line_number=line_number,
                speaker=speaker,
                text=text,
            )
        )

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
    return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", text)).lower()


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
        if coverage >= 0.78:
            status = DialogueMatchStatus.matched
            reason = "成片语音与剧本台词基本一致"
            suggestion = "无需修改；仍建议抽听时间码确认 ASR 没有误识别"
        elif coverage >= 0.42:
            status = DialogueMatchStatus.changed
            reason = "成片语音只匹配到部分剧本台词，可能存在错词、改词或 ASR 误识别"
            suggestion = "回看对应时间码，确认后补录台词或将现场改词更新进剧本版本"
        else:
            status = DialogueMatchStatus.missing
            reason = "未在成片语音中稳定找到这句剧本台词"
            suggestion = "检查是否漏拍、漏录、被剪掉，或 ASR 因噪声未识别"
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
                reason=reason,
                suggestion=suggestion,
            )
        )

    # 如果某个 ASR 片段的大部分字符没有参与任何匹配，将它作为疑似临场加词。
    for segment, (left, right) in zip(transcript_segments, transcript_ranges):
        segment_length = max(1, right - left)
        matched = sum(position in matched_actual_positions for position in range(left, right))
        if segment_length < 2 or matched / segment_length >= 0.45:
            continue
        alignments.append(
            DialogueAlignment(
                id=f"alignment_extra_{segment.id}",
                status=DialogueMatchStatus.extra,
                recognized_text=segment.text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                similarity=matched / segment_length,
                reason="这段成片语音未能对应到剧本台词，可能是临场加词、环境人声或 ASR 误识别",
                suggestion="回看对应时间码；若为有效临场改词，请同步更新剧本并保存新版本",
            )
        )

    return alignments, matcher.ratio()


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
    def __init__(self, transcriber: SpeechTranscriber) -> None:
        self._transcriber = transcriber

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
        parse_result = parse_script_dialogues(script_text)
        script_dialogues = parse_result.dialogues
        alignments, overall_similarity = align_dialogues(
            script_dialogues, transcription.segments
        )
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
            transcript_segments=transcription.segments,
            script_dialogues=script_dialogues,
            ignored_script_lines=parse_result.ignored_lines,
            alignments=alignments,
            overall_similarity=overall_similarity,
            matched_count=counts[DialogueMatchStatus.matched],
            changed_count=counts[DialogueMatchStatus.changed],
            missing_count=counts[DialogueMatchStatus.missing],
            extra_count=counts[DialogueMatchStatus.extra],
            quality=quality,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            created_at=created_at or datetime.now(timezone.utc),
        )


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
    return selected[0].start_ms, selected[-1].end_ms, "".join(item.text for item in selected)


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
