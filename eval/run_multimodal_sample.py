"""在授权视频与剧本上运行可复现的多模态音频回归。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from services.audio_review_service import (
    AudioReviewService,
    FasterWhisperTranscriber,
    RapidOcrSubtitleReader,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("script", type=Path)
    parser.add_argument("--model", choices=("tiny", "base", "small"), default="base")
    parser.add_argument("--speaker-count", type=int, default=0)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    script_text = args.script.read_text(encoding="utf-8-sig")
    with tempfile.TemporaryDirectory(prefix="scriptlint_eval_") as temp_dir:
        report = AudioReviewService(
            FasterWhisperTranscriber(args.model),
            subtitle_reader=RapidOcrSubtitleReader() if args.ocr else None,
        ).review_video(
            video_path=args.video,
            wav_path=Path(temp_dir) / "audio.wav",
            script_text=script_text,
            source_name=args.video.name,
            enable_speaker_clustering=True,
            speaker_count=args.speaker_count,
        )
    payload = report.model_dump(mode="json")
    summary = {
        "dialogues": len(report.script_dialogues),
        "matched": report.matched_count,
        "changed": report.changed_count,
        "missing": report.missing_count,
        "unverified": report.unverified_count,
        "extra": report.extra_count,
        "speaker_clusters": len(report.speaker_clusters),
        "speaker_roles": {
            item.tag: {
                "role": item.mapped_role,
                "confidence": item.role_confidence,
                "segments": item.segment_count,
            }
            for item in report.speaker_clusters
        },
        "speaker_consistency_issues": len(report.speaker_consistency_issues),
        "elapsed_seconds": round(report.elapsed_ms / 1000, 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
