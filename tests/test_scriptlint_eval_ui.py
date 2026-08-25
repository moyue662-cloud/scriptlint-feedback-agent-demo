from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from eval.run_scriptlint_eval import load_scriptlint_eval, run_scriptlint_eval


APP_PATH = Path(__file__).parents[1] / "scriptlint_app.py"


def _navigate(app: AppTest, label: str) -> AppTest:
    return app.radio[0].set_value(label).run(timeout=20)


def test_scriptlint_eval_fixture_has_required_guard_categories():
    fixture = load_scriptlint_eval()
    categories = {case.category for case in fixture.cases}
    assert fixture.data_label == "人工构造 · Eval"
    assert len(fixture.cases) == 11
    assert {"should_apply", "should_ignore", "rule_conflict"} <= categories
    assert {"confirmation_gate", "project_isolation"} <= categories


def test_confirmed_memory_outperforms_no_memory_on_fixed_eval():
    result = run_scriptlint_eval()
    reports = {report["mode"]: report for report in result["reports"]}
    baseline = reports["no_memory"]
    memory = reports["confirmed_memory"]

    assert baseline["finding_exact_match_rate"] < memory["finding_exact_match_rate"]
    assert memory["finding_exact_match_rate"] == 1.0
    assert memory["decision_exact_match_rate"] == 1.0
    assert result["same_type_error_reduction"] == 1.0
    assert result["guard_pass_rate"] == 1.0
    assert result["cross_project_leakage"] == 0
    assert memory["model_call_count"] == 0
    assert memory["avg_estimated_memory_tokens"] > 0


def test_streamlit_demo_click_path_changes_after_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    app = _navigate(app, "剧本审计")
    assert not app.exception
    project_code = next(item.value for item in app.text_input if item.label == "项目代码")

    next(button for button in app.button if button.label == "保存版本并运行多维审计").click().run(timeout=20)
    assert not app.exception
    assert app.metric[0].value == "2"  # 左右脸矛盾 + 已销毁戒指再次出现
    assert app.metric[1].value == "9"
    assert app.metric[2].value == "0 / 0"

    next(button for button in app.button if button.label == "生成候选规则").click().run(timeout=20)
    assert not app.exception
    assert next(item.value for item in app.text_input if item.label == "项目代码") == project_code
    assert len([button for button in app.button if button.label == "确认并复审"]) == 5

    next(button for button in app.button if button.label == "确认并复审").click().run(timeout=20)
    assert not app.exception
    assert next(item.value for item in app.text_input if item.label == "项目代码") == project_code
    assert app.metric[0].value == "3"
    assert app.metric[2].value == "1 / 1"

    next(button for button in app.button if button.label == "载入后续相似任务").click().run(timeout=20)
    assert next(item.value for item in app.text_input if item.label == "项目代码") == project_code
    assert app.number_input[0].value == 4
    assert "第4集" in app.text_area[0].value
    next(button for button in app.button if button.label == "保存版本并运行多维审计").click().run(timeout=20)
    assert not app.exception
    assert app.metric[0].value == "1"
    assert app.metric[2].value == "1 / 1"


def test_streamlit_evaluation_page_runs_without_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_eval_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    app = _navigate(app, "固定评测")
    app.button[0].click().run(timeout=30)

    assert not app.exception
    assert len(app.metric) == 7
    assert len(app.dataframe) == 1


def test_streamlit_accepts_a_user_fountain_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_upload_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    app = _navigate(app, "剧本审计")
    own_script = "INT. 仓库 - 夜\n林夏左手缠着绷带。\n林夏：账本就在城南仓库。"
    app.file_uploader[0].set_value(
        ("my_episode.fountain", own_script.encode("utf-8"), "text/plain")
    ).run(timeout=20)
    next(button for button in app.button if button.label == "读取此文件").click().run(timeout=20)

    assert not app.exception
    assert app.text_area[0].value == own_script


def test_streamlit_user_validation_page_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_validation_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    app = _navigate(app, "用户验证")

    assert not app.exception
    assert len(app.metric) == 6
    assert app.metric[0].value == "0"
    assert len(app.text_input) >= 1
    assert len(app.checkbox) == 1


def test_audio_review_is_homepage_and_requires_video(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_audio_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

    assert not app.exception
    assert app.radio[0].value == "视频音频审片"
    assert app.file_uploader[0].label == "上传短剧成片"
    assert app.file_uploader[1].label == "导入成片字幕（可选，SRT/VTT）"
    next(
        button
        for button in app.button
        if button.label == "运行音频 + 字幕 + 画面基础审核"
    ).click().run(timeout=20)
    assert not app.exception
    assert any("请先上传视频文件" in item.value for item in app.warning)


def test_audio_review_accepts_external_subtitle_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_subtitle_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    subtitle = "1\n00:00:01,000 --> 00:00:02,000\n账本在仓库\n"

    app.file_uploader[1].set_value(
        ("episode.srt", subtitle.encode("utf-8"), "application/x-subrip")
    ).run(timeout=20)

    assert not app.exception
    assert any("已选择字幕：episode.srt" in item.value for item in app.caption)
    assert next(
        item for item in app.checkbox if item.label == "启用画面字幕 OCR 交叉确认"
    ).disabled


def test_audio_review_previews_dialogue_and_excludes_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("DP_DB_PATH", str(tmp_path / "scriptlint_audio_preview_ui.db"))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    script = """## 一、作品信息
- 类型：职场黑色幽默
- 原作：《哲学废物进了大模型公司》
## 二、正文
陆衡：先确认这句话有没有证据。
旁白：会议室安静下来。"""

    next(item for item in app.text_area if item.label == "对照剧本").set_value(script).run(
        timeout=20
    )

    assert not app.exception
    assert any("将 2 行送入音频对齐；排除 2 行" in item.value for item in app.success)
    assert len(app.dataframe) == 2
