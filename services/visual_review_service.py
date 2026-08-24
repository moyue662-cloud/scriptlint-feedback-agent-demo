"""非音频画面证据的第一个可运行切片。

本模块只检测黑帧、极端模糊、长时间冻结和镜头变化。它不宣称理解
人物、动作、表情或道具；这些将在后续模型中复用这里的时间码与镜头边界。
"""
from __future__ import annotations

import math
from pathlib import Path
import time

import numpy as np

from schemas.multimodal import (
    VisualIssue,
    VisualIssueType,
    VisualQualityReport,
)
from services.audio_review_service import AudioReviewError


VISUAL_SAMPLE_INTERVAL_MS = 500
MAX_VISUAL_FRAMES = 1440
BLACK_LUMA_THRESHOLD = 9.0
BLACK_STD_THRESHOLD = 7.0
BLUR_LAPLACIAN_THRESHOLD = 4.0
SHOT_DIFFERENCE_THRESHOLD = 32.0
FREEZE_DIFFERENCE_THRESHOLD = 0.18
FREEZE_MIN_DURATION_MS = 2500


def analyze_visual_track(
    video_path: str | Path,
    *,
    sample_interval_ms: int = VISUAL_SAMPLE_INTERVAL_MS,
    max_frames: int = MAX_VISUAL_FRAMES,
) -> VisualQualityReport:
    """顺序抽帧并生成可回看时间码的保守型画面质量候选。"""
    try:
        import av
        import cv2
    except ImportError as exc:  # pragma: no cover - 部署依赖决定
        raise AudioReviewError("画面基础扫描组件未安装。") from exc

    started = time.perf_counter()
    sampled: list[tuple[int, int, float, float, float, float]] = []
    shot_changes = 0
    width = 0
    height = 0
    previous_gray: np.ndarray | None = None
    try:
        with av.open(str(video_path)) as container:
            if not container.streams.video:
                raise AudioReviewError("视频中没有检测到画面轨。")
            stream = container.streams.video[0]
            width = int(stream.width or 0)
            height = int(stream.height or 0)
            duration_ms = round(container.duration / 1000) if container.duration else 0
            interval_ms = max(
                sample_interval_ms,
                math.ceil(duration_ms / max_frames) if duration_ms else sample_interval_ms,
            )
            next_sample_ms = 0
            frame_number = 0
            for frame in container.decode(stream):
                frame_number += 1
                if frame.pts is None or frame.time_base is None:
                    continue
                timestamp_ms = max(0, round(float(frame.pts * frame.time_base) * 1000))
                if timestamp_ms < next_sample_ms:
                    continue
                image = frame.to_ndarray(format="bgr24")
                if image.size == 0:
                    continue
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
                brightness = float(np.mean(gray))
                contrast = float(np.std(gray))
                blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                difference = (
                    0.0
                    if previous_gray is None
                    else float(np.mean(cv2.absdiff(gray, previous_gray)))
                )
                if previous_gray is not None and difference >= SHOT_DIFFERENCE_THRESHOLD:
                    shot_changes += 1
                sampled.append(
                    (timestamp_ms, frame_number, brightness, contrast, blur_score, difference)
                )
                previous_gray = gray
                next_sample_ms = timestamp_ms + interval_ms
                if len(sampled) >= max_frames:
                    break
    except AudioReviewError:
        raise
    except Exception as exc:
        raise AudioReviewError(f"无法扫描视频画面：{exc}") from exc

    if not sampled or width <= 0 or height <= 0:
        raise AudioReviewError("视频没有可用画面帧。")

    # `interval_ms` 是根据片长和帧数上限计算的真实抽帧间隔。
    interval_ms = max(1, interval_ms)
    black = [
        row for row in sampled
        if row[2] <= BLACK_LUMA_THRESHOLD and row[3] <= BLACK_STD_THRESHOLD
    ]
    blurred = [
        row for row in sampled
        if row[2] > BLACK_LUMA_THRESHOLD and row[4] <= BLUR_LAPLACIAN_THRESHOLD
    ]
    issues: list[VisualIssue] = []
    issues.extend(
        _group_frame_issues(
            black,
            issue_type=VisualIssueType.black_frame,
            interval_ms=interval_ms,
            description="画面亮度和对比度极低，疑似黑帧或意外空帧",
            minimum_duration_ms=interval_ms,
            score_index=2,
        )
    )
    issues.extend(
        _group_frame_issues(
            blurred,
            issue_type=VisualIssueType.blur,
            interval_ms=interval_ms,
            description="边缘信息极低，疑似失焦或过度模糊",
            minimum_duration_ms=interval_ms * 2,
            score_index=4,
        )
    )
    freeze_rows = [row for row in sampled[1:] if row[5] <= FREEZE_DIFFERENCE_THRESHOLD]
    issues.extend(
        _group_frame_issues(
            freeze_rows,
            issue_type=VisualIssueType.freeze,
            interval_ms=interval_ms,
            description="连续画面几乎完全不变；需人工区分有意静止镜头与异常卡帧",
            minimum_duration_ms=FREEZE_MIN_DURATION_MS,
            score_index=5,
        )
    )
    return VisualQualityReport(
        sample_interval_ms=interval_ms,
        sampled_frame_count=len(sampled),
        width=width,
        height=height,
        shot_change_count=shot_changes,
        black_frame_count=len(black),
        blur_frame_count=len(blurred),
        freeze_span_count=sum(
            item.issue_type == VisualIssueType.freeze for item in issues
        ),
        issues=sorted(issues, key=lambda item: item.start_ms),
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _group_frame_issues(
    rows: list[tuple[int, int, float, float, float, float]],
    *,
    issue_type: VisualIssueType,
    interval_ms: int,
    description: str,
    minimum_duration_ms: int,
    score_index: int,
) -> list[VisualIssue]:
    if not rows:
        return []
    groups: list[list[tuple[int, int, float, float, float, float]]] = []
    for row in rows:
        if not groups or row[0] - groups[-1][-1][0] > interval_ms * 1.6:
            groups.append([row])
        else:
            groups[-1].append(row)
    output: list[VisualIssue] = []
    for group in groups:
        start_ms = group[0][0]
        end_ms = group[-1][0] + interval_ms
        if end_ms - start_ms < minimum_duration_ms:
            continue
        score = float(sum(row[score_index] for row in group) / len(group))
        output.append(
            VisualIssue(
                id=f"visual_{issue_type.value}_{len(output) + 1:04d}",
                issue_type=issue_type,
                start_ms=start_ms,
                end_ms=end_ms,
                frame_number=group[0][1],
                score=max(0.0, score),
                description=description,
            )
        )
    return output
