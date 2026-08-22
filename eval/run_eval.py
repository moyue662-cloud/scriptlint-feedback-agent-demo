"""运行仓库内固定评测集。

这是可重复的离线 smoke benchmark：重点验证评测指标、记忆应用和跨团队
隔离的计算链路。它不调用模型，因此输出不能冒充线上模型准确率。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 兼容 README 中的 `python eval/run_eval.py` 直接调用；模块调用则无需改路径。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas import AgentRun, DecisionType, RunMode
from schemas.evaluation import ClassifiedItem, MemoryApplicationRecord
from services.evaluation_service import EvaluationService


CST = timezone(timedelta(hours=8))
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "labels.jsonl"


def load_fixtures(path: Path = FIXTURE_PATH) -> list[dict]:
    """读取并校验 30 条固定样例。"""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_categories = {
        "should_apply": 10,
        "should_ignore": 10,
        "conflict": 5,
        "cross_team": 5,
    }
    counts = {category: sum(1 for row in rows if row["category"] == category) for category in expected_categories}
    if counts != expected_categories:
        raise ValueError(f"固定集分桶不符合规格: {counts}")
    if len(rows) != 30:
        raise ValueError(f"固定集应为 30 条，实际为 {len(rows)} 条")
    return rows


def _predicted_type(row: dict, mode: RunMode) -> DecisionType:
    expected = DecisionType(row["expected_type"])
    if mode == RunMode.decisionpatch:
        return expected
    if mode == RunMode.no_memory and row["category"] == "should_apply":
        # 没有纠正记忆时，试探表达被当成已确认，模拟第一次演示中的可纠正误判。
        return DecisionType.confirmed
    if mode == RunMode.full_history and row["category"] == "cross_team":
        # 全历史基线会把外组表达带入当前上下文，留下可量化的泄漏。
        return DecisionType.confirmed
    return expected


def _did_apply(row: dict, mode: RunMode) -> bool:
    if mode == RunMode.no_memory:
        return False
    if mode == RunMode.decisionpatch:
        return bool(row["memory_should_apply"] and row["memory_team_id"] == row["query_team_id"])
    # 全历史把相关规则都塞入上下文，包括不该跨团队使用的规则。
    return row["category"] in {"should_apply", "cross_team"}


def _report_for(rows: list[dict], mode: RunMode):
    service = EvaluationService()
    items = [
        ClassifiedItem(
            decision_id=row["id"],
            predicted=_predicted_type(row, mode),
            expected=DecisionType(row["expected_type"]),
            evidence_message_ids=[row["evidence_message_id"]],
            valid_evidence=True,
        )
        for row in rows
    ]
    memory_records = [
        MemoryApplicationRecord(
            memory_id=f"mem_{row['id']}",
            memory_team_id=row["memory_team_id"],
            query_team_id=row["query_team_id"],
            should_apply=bool(row["memory_should_apply"] and row["memory_team_id"] == row["query_team_id"]),
            did_apply=_did_apply(row, mode),
            injection_tokens=0 if mode == RunMode.no_memory else (18 if mode == RunMode.decisionpatch else 260),
        )
        for row in rows
    ]
    now = datetime.now(CST)
    input_tokens = {RunMode.no_memory: 240, RunMode.full_history: 1680, RunMode.decisionpatch: 330}[mode]
    memory_tokens = {RunMode.no_memory: 0, RunMode.full_history: 260, RunMode.decisionpatch: 18}[mode]
    runs = [
        AgentRun(
            id=f"eval_{mode.value}_{index:02d}",
            team_id="team_demo",
            project_id="project_demo",
            mode=mode,
            latency_ms=row["latency_ms"] + (40 if mode == RunMode.full_history else 0),
            input_tokens=input_tokens,
            memory_tokens=memory_tokens,
            output_tokens=120,
            memory_hit_count=1 if _did_apply(row, mode) else 0,
            memory_applied_count=1 if _did_apply(row, mode) else 0,
            created_at=now,
        )
        for index, row in enumerate(rows)
    ]
    return service.build_report(
        mode=mode,
        items=items,
        memory_records=memory_records,
        runs=runs,
        same_type_error_reduction=1.0 if mode == RunMode.decisionpatch else None,
    )


def run_offline_eval() -> dict:
    """返回 Streamlit 和 CLI 共用的 JSON-safe 评测结果。"""
    rows = load_fixtures()
    reports = [_report_for(rows, mode) for mode in RunMode]
    return {
        "fixture_count": len(rows),
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "reports": [report.model_dump(mode="json") for report in reports],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DecisionPatch fixed offline evaluation")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    result = run_offline_eval()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"DecisionPatch offline smoke benchmark · {result['fixture_count']} fixtures")
    for report in result["reports"]:
        c = report["classification"]
        m = report["memory"]
        cost = report["cost"]
        print(
            f"{report['mode']:14} accuracy={c['accuracy']:.0%} "
            f"memory_precision={m['precision']:.0%} misuse={m['misuse_rate']:.0%} "
            f"leakage={m['cross_team_leakage']} p95={cost['p95_latency_ms']:.0f}ms"
        )


if __name__ == "__main__":
    main()
