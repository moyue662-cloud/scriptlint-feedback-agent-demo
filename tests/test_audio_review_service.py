from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import math
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from schemas.multimodal import (
    AudioQualityMetrics,
    DialogueAlignment,
    DialogueMatchStatus,
    SubtitleObservation,
    TranscriptSegment,
)
from services import audio_review_service as audio_module
from services.audio_review_service import (
    AudioReviewError,
    AudioReviewService,
    FasterWhisperTranscriber,
    TranscriptionResult,
    align_dialogues,
    assess_text_equivalence,
    build_asr_context,
    extract_audio_track,
    extract_script_dialogues,
    extract_subtitle_observations,
    fuse_subtitle_evidence,
    normalize_dialogue,
    parse_script_dialogues,
    to_simplified_chinese,
)


def _segment(index: int, text: str, start: int, end: int) -> TranscriptSegment:
    return TranscriptSegment(
        id=f"segment_{index}",
        start_ms=start,
        end_ms=end,
        text=text,
        confidence=0.9,
    )


def test_extract_script_dialogues_keeps_speaker_and_line_number():
    rows = extract_script_dialogues(
        "第1集 内景 夜\n林夏（压低声音）：账本在仓库。\n周远: 我现在就去。"
    )

    assert [(row.line_number, row.speaker, row.text) for row in rows] == [
        (2, "林夏", "账本在仓库。"),
        (3, "周远", "我现在就去。"),
    ]


def test_markdown_metadata_title_and_character_background_are_not_dialogue():
    script = """## PandaSuite 全文动画剧本
> 本稿根据当前项目中的剧情整理而成。

## 一、作品信息
- 类型：熊猫头表情包沙雕动画 / 职场黑色幽默 / AI 产品与哲学讽刺
- 原作：《哲学废物进了大模型公司》
- 动画结构：10 个连续 Scene
- 当前编译时长：约 333 秒
- 当前画面规格：1280x720
- 核心人物：陆衡、赵启明、顾晚
- 核心主题：模型说出一句话之前，先判断有没有证据。
- 核心反转：高分不等于安全。

## 二、人物设定
### 陆衡
哲学背景，进入大模型公司做评测与对齐。

## 三、正文
陆衡：我只是想先确认这句话有没有证据。
赵启明（冷笑）：你又在浪费时间。
旁白：会议室突然安静下来。"""

    result = parse_script_dialogues(script)

    assert [(row.speaker, row.text) for row in result.dialogues] == [
        ("陆衡", "我只是想先确认这句话有没有证据。"),
        ("赵启明", "你又在浪费时间。"),
        ("旁白", "会议室突然安静下来。"),
    ]
    assert "陆衡" in result.discovered_characters
    ignored = {row.label: row for row in result.ignored_lines}
    assert "类型" in ignored
    assert "原作" in ignored
    assert "动画结构" in ignored
    assert all(row.line_number < 19 for row in result.ignored_lines)


def test_metadata_labels_are_excluded_even_without_markdown_section():
    result = parse_script_dialogues(
        "剧名：《雨夜便利店》\n场景1：会议室 日 内\n- 林夏：账本在仓库。\n**周远**：我现在就去。"
    )

    assert [(row.speaker, row.text) for row in result.dialogues] == [
        ("林夏", "账本在仓库。"),
        ("周远", "我现在就去。"),
    ]
    assert [row.label for row in result.ignored_lines] == ["剧名", "场景1"]


def test_markdown_speaker_cue_uses_following_paragraph_as_dialogue():
    script = """## 三、正文
**赵启明**（嘲讽，dismiss 动作）：

走错了。大模型在对面，这边教的是存在是否存在。

**顾晚：**

陆衡是在这儿答辩吗？

**赵启明**（得意，smug 表情，dismiss 动作）：

澄思来挖哲学家？下个月是不是还要招占星的？"""

    result = parse_script_dialogues(script)

    assert [(row.line_number, row.speaker, row.text) for row in result.dialogues] == [
        (4, "赵启明", "走错了。大模型在对面，这边教的是存在是否存在。"),
        (8, "顾晚", "陆衡是在这儿答辩吗？"),
        (12, "赵启明", "澄思来挖哲学家？下个月是不是还要招占星的？"),
    ]
    assert all(row.text != "**" for row in result.dialogues)


def test_formatting_and_silence_symbols_never_become_dialogue():
    script = """## 正文
旁白：**

***

顾晚：——
赵启明：真正说出口的内容。"""

    result = parse_script_dialogues(script)

    assert [(row.speaker, row.text) for row in result.dialogues] == [
        ("赵启明", "真正说出口的内容。")
    ]
    assert {row.label for row in result.ignored_lines} == {"旁白", "顾晚"}


def test_normalize_dialogue_removes_punctuation_but_keeps_meaningful_text():
    assert normalize_dialogue("账本，在 A-3 仓库！") == "账本在a3仓库"


def test_traditional_asr_is_converted_to_simplified_chinese():
    assert to_simplified_chinese("先讓他配說話") == "先让他配说话"
    assert normalize_dialogue("項目暫停。") == "项目暂停"


def test_tone_aware_phonetic_equivalence_accepts_same_pronunciation():
    result = assess_text_equivalence("先让它配说话。", "先讓他配說話")

    assert result.kind == "读音一致"
    assert result.phonetic_similarity == pytest.approx(1.0)


def test_lightweight_semantics_accepts_safe_synonym_but_rejects_opposite():
    equivalent = assess_text_equivalence("马上开始", "立刻开始")
    opposite = assess_text_equivalence("把门打开", "把门关上")

    assert equivalent.kind == "轻量语义一致"
    assert opposite.kind is None


def test_exact_audio_transcript_matches_script_across_different_segments():
    rows = extract_script_dialogues("林夏：账本在仓库。\n周远：我现在就去！")
    alignments, score = align_dialogues(
        rows,
        [
            _segment(1, "账本在", 0, 800),
            _segment(2, "仓库，我现在就去", 800, 2400),
        ],
    )

    assert score == pytest.approx(1.0)
    assert [item.status for item in alignments] == [
        DialogueMatchStatus.matched,
        DialogueMatchStatus.matched,
    ]
    assert alignments[0].start_ms == 0
    assert alignments[1].end_ms == 2400


def test_audio_homophone_matching_marks_screenshot_case_as_correct():
    rows = extract_script_dialogues("陆衡：先让它配说话。")

    alignments, _ = align_dialogues(
        rows,
        [_segment(1, "先讓他配說話", 330430, 331930)],
    )

    assert len(alignments) == 1
    assert alignments[0].status == DialogueMatchStatus.matched
    assert alignments[0].recognized_text == "先让他配说话"
    assert alignments[0].resolved_by_audio is True
    assert alignments[0].evidence_match_basis == "音频与剧本读音一致"


def test_non_speech_dash_is_never_reported_as_extra_speech():
    rows = extract_script_dialogues("陆衡：先让它说话。")

    alignments, _ = align_dialogues(rows, [_segment(1, "——", 0, 600)])

    assert [item.status for item in alignments] == [DialogueMatchStatus.missing]


def test_alignment_reports_changed_missing_and_extra_speech():
    rows = extract_script_dialogues(
        "林夏：账本就在城南仓库。\n周远：你留在这里等我。"
    )
    alignments, score = align_dialogues(
        rows,
        [
            _segment(1, "账本在城北仓库", 1000, 2600),
            _segment(2, "这句话完全不在剧本里", 3000, 4800),
        ],
    )

    statuses = [item.status for item in alignments]
    assert DialogueMatchStatus.changed in statuses
    assert DialogueMatchStatus.missing in statuses
    assert DialogueMatchStatus.extra in statuses
    assert 0 < score < 1


def test_alignment_requires_character_dialogue_format():
    with pytest.raises(AudioReviewError, match="角色：台词"):
        align_dialogues([], [_segment(1, "你好", 0, 500)])


def test_subtitle_can_resolve_asr_homophone_change():
    alignment = DialogueAlignment(
        id="alignment_homophone",
        status=DialogueMatchStatus.changed,
        script_line_number=80,
        speaker="旁白",
        expected_text="澄思智能的商务车迷路，停在了哲学楼门口。",
        recognized_text="城司智能的商务车迷路停在了折皿龙门口",
        start_ms=0,
        end_ms=3520,
        similarity=0.68,
        reason="音频部分匹配",
        suggestion="复核",
    )
    subtitle = SubtitleObservation(
        id="subtitle_1",
        start_ms=0,
        end_ms=3500,
        frame_number=1,
        text="澄思智能的商务车迷路，停在了哲学楼门口。",
        confidence=0.96,
    )

    fused, rescued = fuse_subtitle_evidence([alignment], [subtitle])

    assert rescued == 1
    assert fused[0].status == DialogueMatchStatus.matched
    assert fused[0].resolved_by_subtitle is True
    assert fused[0].subtitle_text == subtitle.text


def test_subtitle_rescue_removes_overlapping_duplicate_extra_speech():
    changed = DialogueAlignment(
        id="alignment_changed",
        status=DialogueMatchStatus.changed,
        script_line_number=80,
        speaker="陆衡",
        expected_text="先让它配说话。",
        recognized_text="先让他配说话",
        start_ms=1000,
        end_ms=2200,
        similarity=0.7,
        reason="部分匹配",
        suggestion="复核",
    )
    duplicate_extra = DialogueAlignment(
        id="alignment_extra_same_segment",
        status=DialogueMatchStatus.extra,
        recognized_text="先让他配说话",
        start_ms=1000,
        end_ms=2200,
        similarity=0.2,
        reason="未匹配",
        suggestion="复核",
    )
    subtitle = SubtitleObservation(
        id="subtitle_same_segment",
        start_ms=1000,
        end_ms=2200,
        frame_number=12,
        text="先让它配说话。",
        confidence=0.98,
    )

    fused, rescued = fuse_subtitle_evidence(
        [changed, duplicate_extra], [subtitle]
    )

    assert rescued == 1
    assert len(fused) == 1
    assert fused[0].status == DialogueMatchStatus.matched


def test_subtitle_does_not_hide_missing_audio():
    alignment = DialogueAlignment(
        id="alignment_missing_audio",
        status=DialogueMatchStatus.missing,
        script_line_number=617,
        speaker="赵启明",
        expected_text="他才来几周？",
        similarity=0.1,
        reason="音频未找到",
        suggestion="复核",
    )
    subtitle = SubtitleObservation(
        id="subtitle_2",
        start_ms=235000,
        end_ms=237000,
        frame_number=100,
        text="他才来几周？",
        confidence=0.93,
    )

    fused, rescued = fuse_subtitle_evidence([alignment], [subtitle])

    assert rescued == 0
    assert fused[0].status == DialogueMatchStatus.missing
    assert "字幕不能证明实际收音完整" in fused[0].reason


def test_subtitle_rescues_low_confidence_asr_when_speech_overlaps():
    alignment = DialogueAlignment(
        id="alignment_garbled_asr",
        status=DialogueMatchStatus.missing,
        script_line_number=595,
        speaker="赵启明",
        expected_text="政策是文本，文本能检索，检索就能答。",
        recognized_text="正则是纹本纹本能减锁减锁就能打",
        start_ms=216890,
        end_ms=220130,
        similarity=0.18,
        reason="音频未稳定识别",
        suggestion="复核",
    )
    subtitle = SubtitleObservation(
        id="subtitle_exact_script",
        start_ms=218530,
        end_ms=220030,
        frame_number=100,
        text="政策是文本，文本能检索，检索就能答。",
        confidence=0.96,
    )

    fused, rescued = fuse_subtitle_evidence([alignment], [subtitle])

    assert rescued == 1
    assert fused[0].status == DialogueMatchStatus.matched
    assert fused[0].resolved_by_subtitle is True
    assert "同时间段检测到语音" in fused[0].evidence_match_basis
    assert "不把 ASR 错字计为漏词" in fused[0].reason


def test_asr_context_uses_terms_without_copying_full_dialogue():
    parsed = parse_script_dialogues(
        "陆衡：政策是文本，文本能检索，检索就能答。\n赵启明：项目暂停。"
    )

    prompt, hotwords = build_asr_context(parsed, "澄思智能、哲学楼")

    assert "忠实按实际发音转写" in prompt
    assert "政策是文本，文本能检索" not in prompt
    assert hotwords is not None
    for term in ("陆衡", "赵启明", "政策", "文本", "检索", "项目", "澄思智能", "哲学楼"):
        assert term in hotwords


def test_faster_whisper_uses_multi_candidate_chinese_decode_options():
    captured: dict[str, object] = {}

    class _Model:
        def transcribe(self, audio_path, **kwargs):
            captured["audio_path"] = audio_path
            captured.update(kwargs)
            return (
                [
                    SimpleNamespace(
                        start=0.0,
                        end=1.2,
                        text=" 政策是文本 ",
                        avg_logprob=-0.1,
                    )
                ],
                SimpleNamespace(language="zh", language_probability=0.99),
            )

    transcriber = object.__new__(FasterWhisperTranscriber)
    transcriber.model_name = "base"
    transcriber._model = _Model()

    result = transcriber.transcribe(
        "clip.wav",
        initial_prompt="中文短剧对白",
        hotwords="陆衡 政策 文本",
    )

    assert result.segments[0].text == "政策是文本"
    assert captured["language"] == "zh"
    assert captured["beam_size"] == 5
    assert captured["condition_on_previous_text"] is True
    assert captured["initial_prompt"] == "中文短剧对白"
    assert captured["hotwords"] == "陆衡 政策 文本"


class _FakeSubtitleReader:
    model_name = "fake-ocr"

    def recognize(self, _image):
        return [("项目暂停", 0.95)]


def test_extract_subtitle_observations_samples_and_deduplicates_video(tmp_path):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    video_path = tmp_path / "subtitle.mp4"
    with av.open(str(video_path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width = 320
        stream.height = 180
        stream.pix_fmt = "yuv420p"
        for index in range(4):
            image = np.zeros((180, 320, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts = index
            frame.time_base = Fraction(1, 2)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    observations, frame_count = extract_subtitle_observations(
        video_path,
        _FakeSubtitleReader(),
        sample_interval_ms=400,
        max_frames=10,
    )

    assert frame_count >= 2
    assert len(observations) == 1
    assert observations[0].text == "项目暂停"
    assert observations[0].end_ms > observations[0].start_ms


class _FakeTranscriber:
    model_name = "fake-tiny"

    def transcribe(self, _audio_path, **_kwargs):
        return TranscriptionResult(
            segments=[_segment(1, "账本在仓库", 200, 1200)],
            language="zh",
            language_probability=0.99,
        )


class _StaleTranscriptSegment(BaseModel):
    """模拟 Streamlit 热更新前由旧模块创建、但字段契约相同的对象。"""

    id: str
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


class _CachedOldTranscriber:
    model_name = "cached-old-tiny"

    def transcribe(self, _audio_path, **_kwargs):
        return TranscriptionResult(
            segments=[
                _StaleTranscriptSegment(
                    id="old_asr_1",
                    start_ms=200,
                    end_ms=1200,
                    text="账本在仓库",
                    confidence=0.91,
                )
            ],
            language="zh",
            language_probability=0.98,
        )


def test_review_video_builds_report_with_hash_and_quality(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"not-a-real-video")
    wav_path = tmp_path / "clip.wav"
    expected_quality = AudioQualityMetrics(
        duration_ms=1400,
        sample_rate=16000,
        channels=1,
        rms_dbfs=-18,
        peak_dbfs=-2,
        clipping_ratio=0,
        silence_ratio=0.1,
    )
    monkeypatch.setattr(audio_module, "extract_audio_track", lambda *_: expected_quality)

    report = AudioReviewService(_FakeTranscriber()).review_video(
        video_path=video_path,
        wav_path=wav_path,
        script_text="类型：悬疑短剧\n林夏：账本在仓库。",
        source_name="clip.mp4",
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )

    assert report.matched_count == 1
    assert report.missing_count == 0
    assert report.quality == expected_quality
    assert report.detected_language == "zh"
    assert report.ignored_script_lines[0].label == "类型"
    assert len(report.content_hash) == 64
    assert len(report.script_hash) == 64


def test_review_video_accepts_cached_segments_from_old_module(monkeypatch, tmp_path):
    video_path = tmp_path / "cached-module.mp4"
    video_path.write_bytes(b"not-a-real-video")
    quality = AudioQualityMetrics(
        duration_ms=1400,
        sample_rate=16000,
        channels=1,
        rms_dbfs=-18,
        peak_dbfs=-2,
        clipping_ratio=0,
        silence_ratio=0.1,
    )
    monkeypatch.setattr(audio_module, "extract_audio_track", lambda *_: quality)

    report = AudioReviewService(_CachedOldTranscriber()).review_video(
        video_path=video_path,
        wav_path=tmp_path / "cached-module.wav",
        script_text="林夏：账本在仓库。",
        source_name="cached-module.mp4",
    )

    assert report.matched_count == 1
    assert report.transcript_segments[0].text == "账本在仓库"
    assert isinstance(report.transcript_segments[0], TranscriptSegment)


def test_extract_audio_track_from_mp4_container(tmp_path):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    video_path = tmp_path / "tone.mp4"
    wav_path = tmp_path / "tone.wav"
    sample_rate = 16000
    sample_count = sample_rate
    timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
    samples = (np.sin(2 * math.pi * 440 * timeline) * 0.25 * 32767).astype(np.int16)

    with av.open(str(video_path), mode="w") as container:
        stream = container.add_stream("aac", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    metrics = extract_audio_track(video_path, wav_path)

    assert wav_path.exists()
    assert metrics.sample_rate == 16000
    assert metrics.channels == 1
    assert 900 <= metrics.duration_ms <= 1100
    assert metrics.rms_dbfs > -20
    assert metrics.clipping_ratio == 0
