"""对一组本地剧本与成片运行可重复的音频/字幕评测。

该工具不把输入素材写入仓库。完整模式保存脱敏后的文本证据 JSON；recompute
模式复用这些证据，快速验证新的对齐与证据融合算法。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from schemas.multimodal import (
    AudioReviewReport,
    DialogueMatchStatus,
    SubtitleObservation,
    TranscriptSegment,
)
from services.audio_review_service import (
    AudioReviewService,
    FasterWhisperTranscriber,
    RapidOcrSubtitleReader,
    align_dialogues,
    extract_subtitle_observations,
    fuse_subtitle_evidence,
    parse_script_dialogues,
)


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _summary(
    *,
    alignments: list,
    dialogue_count: int,
    transcript_count: int,
    subtitle_count: int,
    overall_similarity: float,
) -> dict[str, object]:
    counts = {
        status.value: sum(
            _status_value(item.status) == status.value for item in alignments
        )
        for status in DialogueMatchStatus
    }
    candidate_errors = counts[DialogueMatchStatus.changed.value] + counts[
        DialogueMatchStatus.missing.value
    ]
    issues = [
        {
            "status": _status_value(item.status),
            "line": item.script_line_number,
            "speaker": item.speaker,
            "expected": item.expected_text,
            "recognized": item.recognized_text,
            "subtitle": item.subtitle_text,
            "start_ms": item.start_ms,
            "end_ms": item.end_ms,
            "similarity": item.similarity,
            "reason": item.reason,
        }
        for item in alignments
        if _status_value(item.status)
        in {
            DialogueMatchStatus.changed.value,
            DialogueMatchStatus.missing.value,
        }
    ]
    return {
        "dialogue_count": dialogue_count,
        "candidate_error_count": candidate_errors,
        "candidate_error_rate": (
            candidate_errors / dialogue_count if dialogue_count else 0.0
        ),
        "counts": counts,
        "transcript_segment_count": transcript_count,
        "subtitle_observation_count": subtitle_count,
        "overall_character_similarity": overall_similarity,
        "issues": issues,
    }


def _console_summary(result: dict[str, object]) -> dict[str, object]:
    compact = dict(result)
    issues = list(compact.pop("issues", []))
    compact["issue_preview"] = issues[:12]
    compact["issue_preview_truncated"] = len(issues) > 12
    return compact


def _recompute(script_text: str, report: AudioReviewReport) -> dict[str, object]:
    parsed = parse_script_dialogues(script_text)
    segments = [
        TranscriptSegment.model_validate(item.model_dump(mode="python"))
        for item in report.transcript_segments
    ]
    subtitles = [
        SubtitleObservation.model_validate(item.model_dump(mode="python"))
        for item in report.subtitle_observations
    ]
    alignments, similarity = align_dialogues(parsed.dialogues, segments)
    alignments, _ = fuse_subtitle_evidence(alignments, subtitles, segments)
    return _summary(
        alignments=alignments,
        dialogue_count=len(parsed.dialogues),
        transcript_count=len(segments),
        subtitle_count=len(subtitles),
        overall_similarity=similarity,
    )


def _refresh_ocr(
    *,
    script_text: str,
    report: AudioReviewReport,
    video_path: Path,
) -> tuple[AudioReviewReport, dict[str, object]]:
    parsed = parse_script_dialogues(script_text)
    segments = [
        TranscriptSegment.model_validate(item.model_dump(mode="python"))
        for item in report.transcript_segments
    ]
    reader = RapidOcrSubtitleReader()
    observations, frame_count = extract_subtitle_observations(
        video_path,
        reader,
        target_timestamps_ms=[
            (item.start_ms + item.end_ms) // 2 for item in segments
        ],
    )
    alignments, similarity = align_dialogues(parsed.dialogues, segments)
    alignments, rescued = fuse_subtitle_evidence(
        alignments,
        observations,
        segments,
    )
    counts = {
        status: sum(item.status == status for item in alignments)
        for status in DialogueMatchStatus
    }
    updated = report.model_copy(
        update={
            "script_dialogues": parsed.dialogues,
            "ignored_script_lines": parsed.ignored_lines,
            "subtitle_observations": observations,
            "ocr_model_name": reader.model_name,
            "ocr_frame_count": frame_count,
            "ocr_rescued_count": rescued,
            "ocr_warnings": [],
            "alignments": alignments,
            "overall_similarity": similarity,
            "matched_count": counts[DialogueMatchStatus.matched],
            "changed_count": counts[DialogueMatchStatus.changed],
            "missing_count": counts[DialogueMatchStatus.missing],
            "extra_count": counts[DialogueMatchStatus.extra],
        }
    )
    return updated, _summary(
        alignments=alignments,
        dialogue_count=len(parsed.dialogues),
        transcript_count=len(segments),
        subtitle_count=len(observations),
        overall_similarity=similarity,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--model", choices=("tiny", "base", "small"), default="base")
    parser.add_argument("--terms", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recompute", type=Path)
    parser.add_argument("--refresh-ocr", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()

    script_text = args.script.read_text(encoding="utf-8")
    if args.recompute:
        report = AudioReviewReport.model_validate_json(
            args.recompute.read_text(encoding="utf-8")
        )
        if args.refresh_ocr:
            if args.video is None:
                parser.error("--refresh-ocr 需要 --video")
            report, result = _refresh_ocr(
                script_text=script_text,
                report=report,
                video_path=args.video,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            print(json.dumps(_console_summary(result), ensure_ascii=False, indent=2))
            return
        result = _recompute(script_text, report)
        print(json.dumps(_console_summary(result), ensure_ascii=False, indent=2))
        return

    if args.video is None:
        parser.error("完整评测需要 --video")
    reader = None if args.no_ocr else RapidOcrSubtitleReader()
    service = AudioReviewService(
        FasterWhisperTranscriber(args.model),
        subtitle_reader=reader,
    )
    with tempfile.TemporaryDirectory(prefix="scriptlint_media_eval_") as temp_dir:
        report = service.review_video(
            video_path=args.video,
            wav_path=Path(temp_dir) / "audio.wav",
            script_text=script_text,
            source_name=args.video.name,
            asr_terms=args.terms,
            created_at=datetime.now(timezone.utc),
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    result = _summary(
        alignments=report.alignments,
        dialogue_count=len(report.script_dialogues),
        transcript_count=len(report.transcript_segments),
        subtitle_count=len(report.subtitle_observations),
        overall_similarity=report.overall_similarity,
    )
    print(json.dumps(_console_summary(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
