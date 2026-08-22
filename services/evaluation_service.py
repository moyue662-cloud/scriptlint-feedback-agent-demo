"""评测服务：指标计算。

对应规格第 10 节评测方案。所有指标均为「目标，非已取得结果」，
只有实际运行评测脚本后才能写入路演稿（规格 §10.2）。

本服务接收已对齐的「预测 - 标注」结果与记忆应用记录，
计算分类准确率、证据绑定率、记忆精确率、误用率、跨团队泄漏、
注入量、P95 延迟与同类错误下降（规格 §10.2）。

纯计算，不调模型、不访问持久层——输入由 run_eval.py 对齐后传入。
"""
from __future__ import annotations

from schemas import AgentRun, DecisionType, RunMode
from schemas.evaluation import (
    ClassifiedItem,
    ClassificationMetrics,
    CostMetrics,
    EvaluationReport,
    MemoryApplicationRecord,
    MemoryMetrics,
)

# 需要证据绑定的类型：非 conflict / unknown（规格 §7.3）
_NEEDS_EVIDENCE = {DecisionType.conflict, DecisionType.unknown}


class EvaluationService:
    """评测指标计算服务（规格 §10.2）。

    三组对照（规格 §10.3）：no_memory / full_history / decisionpatch。
    赛题 4 的技术结论必须来自该对照，而非单次成功演示。
    """

    # -- 对象分类准确率 + 证据绑定率（规格 §10.2）--------------------------- #

    def compute_classification(
        self, items: list[ClassifiedItem]
    ) -> ClassificationMetrics:
        """五类对象分类正确数/总数 + 有证据结论/全部结论（规格 §10.2）。"""
        total = len(items)
        if total == 0:
            return ClassificationMetrics()

        correct = sum(1 for it in items if it.predicted == it.expected)

        # 证据绑定：需要证据的结论 = 非 conflict/unknown（规格 §7.3）
        needs_evidence = [it for it in items if it.expected not in _NEEDS_EVIDENCE]
        evidence_total = len(needs_evidence)
        evidence_bound = sum(1 for it in needs_evidence if it.valid_evidence)

        return ClassificationMetrics(
            total=total,
            correct=correct,
            accuracy=correct / total,
            evidence_total=evidence_total,
            evidence_bound=evidence_bound,
            evidence_binding_rate=(
                evidence_bound / evidence_total if evidence_total else 1.0
            ),
        )

    # -- 记忆应用指标（规格 §10.2）---------------------------------------- #

    def compute_memory(
        self, records: list[MemoryApplicationRecord]
    ) -> MemoryMetrics:
        """记忆精确率 + 误用率 + 跨团队泄漏 + 注入量（规格 §10.2）。"""
        if not records:
            return MemoryMetrics()

        applied = [r for r in records if r.did_apply]
        applied_correct = [r for r in applied if r.should_apply]
        misuse = [r for r in applied if not r.should_apply]
        should_not_apply = [r for r in records if not r.should_apply]
        # 跨团队泄漏：使用了其他团队的记忆（规格 §6.5，目标 0）
        leakage = [
            r for r in applied if r.memory_team_id != r.query_team_id
        ]
        max_tokens = max((r.injection_tokens for r in records), default=0)

        return MemoryMetrics(
            applied_total=len(applied),
            applied_correct=len(applied_correct),
            precision=(
                len(applied_correct) / len(applied) if applied else 1.0
            ),
            misuse_count=len(misuse),
            misuse_sample_total=len(should_not_apply),
            misuse_rate=(
                len(misuse) / len(should_not_apply) if should_not_apply else 0.0
            ),
            cross_team_leakage=len(leakage),
            max_injection_tokens=max_tokens,
        )

    # -- 成本与速度指标（规格 §10.2）-------------------------------------- #

    def compute_cost(self, runs: list[AgentRun]) -> CostMetrics:
        """P95 延迟 + 平均 token（规格 §10.2）。"""
        if not runs:
            return CostMetrics()

        latencies = sorted(r.latency_ms for r in runs)
        return CostMetrics(
            run_count=len(runs),
            p95_latency_ms=_percentile(latencies, 95),
            avg_input_tokens=_mean([r.input_tokens for r in runs]),
            avg_memory_tokens=_mean([r.memory_tokens for r in runs]),
            avg_output_tokens=_mean([r.output_tokens for r in runs]),
        )

    # -- 汇总报告（规格 §10.2 / §10.3）------------------------------------ #

    def build_report(
        self,
        *,
        mode: RunMode,
        items: list[ClassifiedItem],
        memory_records: list[MemoryApplicationRecord],
        runs: list[AgentRun],
        same_type_error_reduction: float | None = None,
    ) -> EvaluationReport:
        """汇总三组指标为一份报告（规格 §10.2 / §10.3 三组对照）。

        same_type_error_reduction：反馈前后同类误判变化（规格 §10.2，目标 ≥ 50%）。
        该指标需要前后两次评测对比，由调用方计算后传入。
        """
        return EvaluationReport(
            mode=mode,
            classification=self.compute_classification(items),
            memory=self.compute_memory(memory_records),
            cost=self.compute_cost(runs),
            same_type_error_reduction=same_type_error_reduction,
        )


# --------------------------------------------------------------------------- #
# 统计辅助
# --------------------------------------------------------------------------- #


def _mean(xs: list[int]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _percentile(sorted_vals: list[int], p: float) -> float:
    """线性插值百分位（规格 §10.2 P95）。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)
