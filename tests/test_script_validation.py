from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from repositories import SQLiteRepository
from schemas.scriptlint import (
    ScriptUserValidation,
    ValidationJudgment,
    ValidationRole,
)
from services.script_validation_service import ScriptValidationService


NOW = datetime(2026, 8, 22, 16, 0, tzinfo=timezone(timedelta(hours=8)))


@pytest.fixture()
def service():
    repo = SQLiteRepository(":memory:")
    repo.init()
    value = ScriptValidationService(repo)
    yield value
    repo.close()


def _item(code: str = "P01", **overrides) -> ScriptUserValidation:
    data = {
        "id": f"validation_{code}",
        "team_id": "team_scriptlint_demo",
        "project_id": "project_rain_store",
        "participant_code": code,
        "role": ValidationRole.student_creator,
        "completed_feedback_loop": True,
        "rule_judgment": ValidationJudgment.correct,
        "explanation_clarity": 4,
        "trace_trust": 5,
        "would_use": True,
        "duration_seconds": 180,
        "comment": "能看懂规则来自哪里",
        "consent": True,
        "created_at": NOW,
    }
    data.update(overrides)
    return ScriptUserValidation(**data)


def test_validation_requires_consent_and_anonymous_code():
    with pytest.raises(ValidationError, match="未同意匿名记录"):
        _item(consent=False)
    with pytest.raises(ValidationError, match="只能包含"):
        _item(code="张 三")


def test_validation_roundtrip_and_duplicate_guard(service):
    service.record(_item())
    rows = service.list(
        team_id="team_scriptlint_demo",
        project_id="project_rain_store",
    )
    assert len(rows) == 1
    assert rows[0].participant_code == "P01"
    assert rows[0].comment == "能看懂规则来自哪里"
    with pytest.raises(sqlite3.IntegrityError):
        service.record(_item(id="validation_duplicate"))


def test_validation_summary_only_becomes_directional_after_three_correct_users(service):
    for code, clarity in (("P01", 3), ("P02", 4), ("P03", 5)):
        service.record(_item(code=code, explanation_clarity=clarity))
    summary = service.summarize(
        team_id="team_scriptlint_demo",
        project_id="project_rain_store",
    )
    assert summary.participant_count == 3
    assert summary.completion_rate == 1.0
    assert summary.correct_rate == 1.0
    assert summary.avg_explanation_clarity == 4.0
    assert summary.avg_trace_trust == 5.0
    assert summary.would_use_rate == 1.0
    assert summary.ready_for_directional_claim is True


def test_validation_scope_isolation(service):
    service.record(_item())
    assert service.list(team_id="another_team", project_id="project_rain_store") == []
    assert service.list(team_id="team_scriptlint_demo", project_id="another_project") == []


def test_validation_csv_is_anonymous_and_local_scope_fields_are_omitted(service):
    service.record(_item())
    exported = service.export_csv(
        team_id="team_scriptlint_demo",
        project_id="project_rain_store",
    )
    header = exported.splitlines()[0]
    assert "participant_code" in header
    assert "team_id" not in header
    assert "project_id" not in header
    assert "consent" not in header
    assert "P01" in exported
