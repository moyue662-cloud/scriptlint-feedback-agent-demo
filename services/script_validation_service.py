"""少量真实用户验证：匿名记录、汇总和本地导出。"""
from __future__ import annotations

import csv
from io import StringIO
from statistics import mean

from repositories import SQLiteRepository
from schemas.scriptlint import (
    ScriptUserValidation,
    ScriptValidationSummary,
    ValidationJudgment,
)


class ScriptValidationService:
    def __init__(self, repo: SQLiteRepository) -> None:
        self._repo = repo

    def record(self, item: ScriptUserValidation) -> None:
        self._repo.insert_script_validation(item)

    def list(self, *, team_id: str, project_id: str) -> list[ScriptUserValidation]:
        return self._repo.list_script_validations(team_id=team_id, project_id=project_id)

    def summarize(
        self,
        *,
        team_id: str,
        project_id: str,
    ) -> ScriptValidationSummary:
        rows = self.list(team_id=team_id, project_id=project_id)
        if not rows:
            return ScriptValidationSummary(
                participant_count=0,
                completion_rate=0,
                correct_rate=0,
                avg_explanation_clarity=0,
                avg_trace_trust=0,
                would_use_rate=0,
            )
        correct = [row.rule_judgment == ValidationJudgment.correct for row in rows]
        return ScriptValidationSummary(
            participant_count=len(rows),
            completion_rate=mean(row.completed_feedback_loop for row in rows),
            correct_rate=mean(correct),
            avg_explanation_clarity=mean(row.explanation_clarity for row in rows),
            avg_trace_trust=mean(row.trace_trust for row in rows),
            would_use_rate=mean(row.would_use for row in rows),
            # 3–5 人只能支持方向性结论；至少 3 人且无明显正确性失败才显示就绪。
            ready_for_directional_claim=len(rows) >= 3 and mean(correct) >= 0.8,
        )

    def export_csv(self, *, team_id: str, project_id: str) -> str:
        rows = self.list(team_id=team_id, project_id=project_id)
        output = StringIO(newline="")
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "participant_code",
                "role",
                "scenario_id",
                "completed_feedback_loop",
                "rule_judgment",
                "explanation_clarity",
                "trace_trust",
                "would_use",
                "duration_seconds",
                "comment",
                "created_at",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "participant_code": row.participant_code,
                    "role": row.role.value,
                    "scenario_id": row.scenario_id,
                    "completed_feedback_loop": row.completed_feedback_loop,
                    "rule_judgment": row.rule_judgment.value,
                    "explanation_clarity": row.explanation_clarity,
                    "trace_trust": row.trace_trust,
                    "would_use": row.would_use,
                    "duration_seconds": row.duration_seconds or "",
                    "comment": row.comment or "",
                    "created_at": row.created_at.isoformat(),
                }
            )
        return output.getvalue()
