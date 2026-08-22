"""evaluation_service 单元测试（Part 6.3）。

覆盖规格第 10 节评测方案。所有指标均为「目标，非已取得结果」，
只有实际运行评测脚本后才能写入路演稿（规格 §10.2）。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from schemas import AgentRun, DecisionType, RunMode
from schemas.evaluation import (
    ClassifiedItem,
    MemoryApplicationRecord,
)
from services.evaluation_service import EvaluationService

CST = timezone(timedelta(hours=8))
_NOW = datetime(2026, 8, 20, 18, 0, tzinfo=CST)


# ---------- 对象分类准确率 + 证据绑定率（规格 §10.2）----------

def test_classification_accuracy():
    svc = EvaluationService()
    items = [
        ClassifiedItem(decision_id="d1", predicted=DecisionType.proposal, expected=DecisionType.proposal, valid_evidence=True),
        ClassifiedItem(decision_id="d2", predicted=DecisionType.confirmed, expected=DecisionType.confirmed, valid_evidence=True),
        ClassifiedItem(decision_id="d3", predicted=DecisionType.proposal, expected=DecisionType.confirmed, valid_evidence=True),  # 错
        ClassifiedItem(decision_id="d4", predicted=DecisionType.task, expected=DecisionType.task, valid_evidence=True),
    ]
    m = svc.compute_classification(items)
    assert m.total == 4
    assert m.correct == 3
    assert abs(m.accuracy - 0.75) < 1e-9


def test_classification_evidence_binding_rate():
    """需要证据的结论（非 conflict/unknown）必须绑定证据（规格 §7.3）。"""
    svc = EvaluationService()
    items = [
        # confirmed 需要证据，且证据有效
        ClassifiedItem(decision_id="d1", predicted=DecisionType.confirmed, expected=DecisionType.confirmed, valid_evidence=True),
        # task 需要证据，但证据无效
        ClassifiedItem(decision_id="d2", predicted=DecisionType.task, expected=DecisionType.task, valid_evidence=False),
        # conflict 不需要证据
        ClassifiedItem(decision_id="d3", predicted=DecisionType.conflict, expected=DecisionType.conflict, valid_evidence=False),
    ]
    m = svc.compute_classification(items)
    assert m.evidence_total == 2  # confirmed + task
    assert m.evidence_bound == 1  # 只有 d1 有效
    assert abs(m.evidence_binding_rate - 0.5) < 1e-9


def test_classification_empty():
    svc = EvaluationService()
    m = svc.compute_classification([])
    assert m.total == 0
    assert m.accuracy == 0.0


# ---------- 记忆应用指标（规格 §10.2）----------

def test_memory_precision_and_misuse():
    svc = EvaluationService()
    records = [
        # 应应用且应用了 -> 正确
        MemoryApplicationRecord(memory_id="m1", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=True, injection_tokens=100),
        # 应应用但没应用 -> 漏召（不计入误用）
        MemoryApplicationRecord(memory_id="m2", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=False),
        # 不应应用却应用了 -> 误用
        MemoryApplicationRecord(memory_id="m3", memory_team_id="t1", query_team_id="t1", should_apply=False, did_apply=True, injection_tokens=50),
        # 不应应用且没应用 -> 正确忽略
        MemoryApplicationRecord(memory_id="m4", memory_team_id="t1", query_team_id="t1", should_apply=False, did_apply=False),
    ]
    m = svc.compute_memory(records)
    assert m.applied_total == 2  # m1, m3
    assert m.applied_correct == 1  # m1
    assert abs(m.precision - 0.5) < 1e-9  # 1/2
    assert m.misuse_count == 1  # m3
    assert m.misuse_sample_total == 2  # m3, m4
    assert abs(m.misuse_rate - 0.5) < 1e-9  # 1/2


def test_memory_cross_team_leakage_zero():
    """跨团队泄漏目标为 0（规格 §6.5）。"""
    svc = EvaluationService()
    records = [
        MemoryApplicationRecord(memory_id="m1", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=True, injection_tokens=100),
        MemoryApplicationRecord(memory_id="m2", memory_team_id="t2", query_team_id="t1", should_apply=False, did_apply=True, injection_tokens=50),  # 泄漏
    ]
    m = svc.compute_memory(records)
    assert m.cross_team_leakage == 1


def test_memory_max_injection_tokens():
    svc = EvaluationService()
    records = [
        MemoryApplicationRecord(memory_id="m1", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=True, injection_tokens=180),
        MemoryApplicationRecord(memory_id="m2", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=True, injection_tokens=250),
    ]
    m = svc.compute_memory(records)
    assert m.max_injection_tokens == 250


# ---------- 成本与速度指标（规格 §10.2）----------

def test_cost_p95_latency():
    svc = EvaluationService()
    runs = [
        AgentRun(id=f"r{i}", team_id="t1", project_id="p1", latency_ms=lat, created_at=_NOW)
        for i, lat in enumerate([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    ]
    m = svc.compute_cost(runs)
    assert m.run_count == 10
    # P95 of [10..100] 线性插值 ≈ 95.5
    assert 95.0 <= m.p95_latency_ms <= 96.0


def test_cost_avg_tokens():
    svc = EvaluationService()
    runs = [
        AgentRun(id="r1", team_id="t1", project_id="p1", latency_ms=100, input_tokens=200, memory_tokens=150, output_tokens=80, created_at=_NOW),
        AgentRun(id="r2", team_id="t1", project_id="p1", latency_ms=200, input_tokens=400, memory_tokens=250, output_tokens=120, created_at=_NOW),
    ]
    m = svc.compute_cost(runs)
    assert abs(m.avg_input_tokens - 300.0) < 1e-9
    assert abs(m.avg_memory_tokens - 200.0) < 1e-9
    assert abs(m.avg_output_tokens - 100.0) < 1e-9


# ---------- 汇总报告（规格 §10.2 / §10.3 三组对照）----------

def test_build_report_decisionpatch_mode():
    svc = EvaluationService()
    items = [
        ClassifiedItem(decision_id="d1", predicted=DecisionType.proposal, expected=DecisionType.proposal, valid_evidence=True),
    ]
    records = [
        MemoryApplicationRecord(memory_id="m1", memory_team_id="t1", query_team_id="t1", should_apply=True, did_apply=True, injection_tokens=180),
    ]
    runs = [
        AgentRun(id="r1", team_id="t1", project_id="p1", mode=RunMode.decisionpatch, latency_ms=100, memory_tokens=180, created_at=_NOW),
    ]
    report = svc.build_report(
        mode=RunMode.decisionpatch,
        items=items,
        memory_records=records,
        runs=runs,
        same_type_error_reduction=0.6,
    )
    assert report.mode == RunMode.decisionpatch
    assert report.classification.accuracy == 1.0
    assert report.memory.precision == 1.0
    assert report.memory.cross_team_leakage == 0
    assert report.memory.max_injection_tokens == 180
    assert report.cost.run_count == 1
    assert report.same_type_error_reduction == 0.6
