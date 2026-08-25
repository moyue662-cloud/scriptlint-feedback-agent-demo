"""像真实用户一样驱动 Streamlit 页面完成授权媒体验收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).parents[1] / "scriptlint_app.py"


def _by_label(items, label: str):
    return next(item for item in items if item.label == label)


def _raise_page_exceptions(app: AppTest) -> None:
    if not app.exception:
        return
    messages = [str(getattr(item, "value", item)) for item in app.exception]
    raise RuntimeError("；".join(messages))


def _summary(report) -> dict[str, int | float]:
    return {
        "dialogues": len(report.script_dialogues),
        "matched": report.matched_count,
        "changed": report.changed_count,
        "missing": report.missing_count,
        "unverified": report.unverified_count,
        "extra": report.extra_count,
        "speaker_clusters": len(report.speaker_clusters),
        "speaker_mapping_count": report.speaker_mapping_count,
        "speaker_consistency_issues": len(report.speaker_consistency_issues),
        "elapsed_seconds": round(report.elapsed_ms / 1000, 2),
    }


def _dialogue_signature(summary: dict[str, int | float]) -> tuple[int | float, ...]:
    return tuple(
        summary[key]
        for key in ("dialogues", "matched", "changed", "missing", "unverified", "extra")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("script", type=Path)
    parser.add_argument("--model", choices=("tiny", "base", "small"), default="base")
    parser.add_argument("--speaker-count", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    script_text = args.script.read_text(encoding="utf-8-sig")
    video_bytes = args.video.read_bytes()
    with tempfile.TemporaryDirectory(
        prefix="scriptlint_ui_acceptance_", ignore_cleanup_errors=True
    ) as temp_dir:
        os.environ["DP_DB_PATH"] = str(Path(temp_dir) / "acceptance.db")
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        _by_label(app.text_area, "对照剧本").set_value(script_text).run(timeout=30)
        _by_label(app.file_uploader, "上传短剧成片").set_value(
            (args.video.name, video_bytes, "video/mp4")
        ).run(timeout=60)
        _by_label(app.selectbox, "语音模型").set_value(args.model).run(timeout=30)
        _by_label(app.checkbox, "启用画面字幕 OCR 交叉确认").set_value(False).run(
            timeout=30
        )
        _by_label(app.checkbox, "启用画面基础质量扫描（试验）").set_value(
            False
        ).run(timeout=30)
        speaker_toggle = _by_label(
            app.checkbox, "启用轻量说话人声学分组（试验）"
        )
        speaker_toggle.set_value(False).run(timeout=30)
        _by_label(app.button, "运行音频 + 字幕 + 画面基础审核").click().run(
            timeout=360
        )
        _raise_page_exceptions(app)
        baseline = app.session_state["audio_review_report"]
        baseline_summary = _summary(baseline)

        _by_label(
            app.checkbox, "启用轻量说话人声学分组（试验）"
        ).set_value(True).run(timeout=30)
        _by_label(app.number_input, "预计主要说话人数（0 = 自动估计）").set_value(
            args.speaker_count
        ).run(timeout=30)
        _by_label(app.button, "运行音频 + 字幕 + 画面基础审核").click().run(
            timeout=360
        )
        _raise_page_exceptions(app)
        initial = app.session_state["audio_review_report"]
        initial_summary = _summary(initial)
        mapping_button = next(
            (
                item
                for item in app.button
                if item.label == "应用声音组—角色映射"
            ),
            None,
        )
        mapping_applied = False
        mapped_segment_count = initial.speaker_mapping_count
        if mapping_button is not None and initial.speaker_clusters:
            mapping_button.click().run(timeout=60)
            _raise_page_exceptions(app)
            revised = app.session_state["audio_review_report"]
            mapped_segment_count = revised.speaker_mapping_count
            mapping_applied = mapped_segment_count > initial.speaker_mapping_count
        result = {
            "ui_completed_without_exception": not bool(app.exception),
            "speaker_disabled": baseline_summary,
            "speaker_enabled": initial_summary,
            "cluster_mapping_button_present": mapping_button is not None,
            "manual_mapping_applied": mapping_applied,
            "mapped_segment_count_after_confirmation": mapped_segment_count,
            "usefulness_gate": {
                "dialogue_results_unchanged": (
                    _dialogue_signature(baseline_summary)
                    == _dialogue_signature(initial_summary)
                ),
                "produced_multiple_clusters": len(initial.speaker_clusters) >= 2,
                "kept_low_confidence_unmapped": initial.speaker_mapping_count == 0,
                "did_not_emit_speaker_false_alarm": not initial.speaker_consistency_issues,
                "human_confirmation_changes_result": mapping_applied,
            },
        }
        result["acceptance_passed"] = bool(
            result["ui_completed_without_exception"]
            and result["cluster_mapping_button_present"]
            and all(result["usefulness_gate"].values())
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not result["acceptance_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
