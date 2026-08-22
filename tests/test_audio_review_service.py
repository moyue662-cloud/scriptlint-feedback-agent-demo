from __future__ import annotations

from datetime import datetime, timezone
import math

import pytest

from schemas.multimodal import (
    AudioQualityMetrics,
    DialogueMatchStatus,
    TranscriptSegment,
)
from services import audio_review_service as audio_module
from services.audio_review_service import (
    AudioReviewError,
    AudioReviewService,
    TranscriptionResult,
    align_dialogues,
    extract_audio_track,
    extract_script_dialogues,
    normalize_dialogue,
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


def test_normalize_dialogue_removes_punctuation_but_keeps_meaningful_text():
    assert normalize_dialogue("账本，在 A-3 仓库！") == "账本在a3仓库"


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


class _FakeTranscriber:
    model_name = "fake-tiny"

    def transcribe(self, _audio_path):
        return TranscriptionResult(
            segments=[_segment(1, "账本在仓库", 200, 1200)],
            language="zh",
            language_probability=0.99,
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
        script_text="林夏：账本在仓库。",
        source_name="clip.mp4",
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )

    assert report.matched_count == 1
    assert report.missing_count == 0
    assert report.quality == expected_quality
    assert report.detected_language == "zh"
    assert len(report.content_hash) == 64
    assert len(report.script_hash) == 64


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
