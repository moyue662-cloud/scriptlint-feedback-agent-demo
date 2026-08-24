from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from schemas.multimodal import VisualIssueType
from services.visual_review_service import analyze_visual_track


def test_visual_scan_reports_frames_and_freeze_span(tmp_path):
    av = pytest.importorskip("av")
    video_path = tmp_path / "visual.mp4"
    with av.open(str(video_path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width = 320
        stream.height = 180
        stream.pix_fmt = "yuv420p"
        for index in range(14):
            image = np.full((180, 320, 3), 120, dtype=np.uint8)
            if index >= 12:
                image[:, :160] = 230
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts = index
            frame.time_base = Fraction(1, 2)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    report = analyze_visual_track(
        video_path,
        sample_interval_ms=500,
        max_frames=30,
    )

    assert report.sampled_frame_count >= 12
    assert report.width == 320
    assert report.height == 180
    assert report.freeze_span_count >= 1
    assert any(item.issue_type == VisualIssueType.freeze for item in report.issues)


def test_visual_scan_groups_black_frames(tmp_path):
    av = pytest.importorskip("av")
    video_path = tmp_path / "black.mp4"
    with av.open(str(video_path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width = 160
        stream.height = 90
        stream.pix_fmt = "yuv420p"
        for index in range(6):
            image = np.zeros((90, 160, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts = index
            frame.time_base = Fraction(1, 2)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    report = analyze_visual_track(video_path, sample_interval_ms=500)

    assert report.black_frame_count >= 5
    assert any(item.issue_type == VisualIssueType.black_frame for item in report.issues)
