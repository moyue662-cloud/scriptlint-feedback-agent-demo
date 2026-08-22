"""评测指标模型。

对应规格第 10 节评测方案。所有指标均为「目标，非已取得结果」，
只有实际运行评测脚本后才能写入路演稿（规格 §10.2）。

三组对照（规格 §10.3）：no_memory / full_history / decisionpatch。
赛题 4 的技术结论必须来自该对照，而非单次成功演示。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .decision import DecisionType
from .metrics import RunMode


class ClassifiedItem(BaseModel):
    """一条已匹配的「预测 - 标注」对（规格 §10.2 对象分类准确率）。

    匹配逻辑（按消息/主题对齐预测与标注）由 run_eval.py 负责；
    本服务只接收已对齐的结果并计算指标。
    """

    decision_id: str
    predicted: DecisionType
    expected: DecisionType
    evidence_message_ids: list[str] = Field(default_factory=list)
    valid_evidence: bool = False  # 证据是否正确引用了真实存在的消息


class ClassificationMetrics(BaseModel):
    """对象分类与证据绑定指标（规格 §10.2）。"""

    total: int = 0
    correct: int = 0
    accuracy: float = 0.0  # 分类准确率，目标 ≥ 85%
    evidence_total: int = 0  # 需要证据的结论数（非 conflict/unknown）
    evidence_bound: int = 0  # 其中正确绑定证据的
    evidence_binding_rate: float = 0.0  # 证据绑定率，目标 100%


class MemoryApplicationRecord(BaseModel):
    """一条记忆应用的记录（规格 §10.2 记忆指标）。"""

    memory_id: str
    memory_team_id: str  # 该记忆所属团队
    query_team_id: str  # 本轮查询所属团队
    should_apply: bool  # 期望是否应用（标注）
    did_apply: bool  # 实际是否应用
    injection_tokens: int = 0


class MemoryMetrics(BaseModel):
    """记忆应用指标（规格 §10.2）。"""

    applied_total: int = 0  # 全部应用次数
    applied_correct: int = 0  # 正确应用次数
    precision: float = 0.0  # 记忆应用精确率，目标 ≥ 90%
    misuse_count: int = 0  # 不应应用却应用
    misuse_sample_total: int = 0  # 不应应用样例数
    misuse_rate: float = 0.0  # 误用率，目标 ≤ 10%
    cross_team_leakage: int = 0  # 跨团队泄漏，目标 0
    max_injection_tokens: int = 0  # 单次最大注入量，目标 ≤ 300


class CostMetrics(BaseModel):
    """成本与速度指标（规格 §10.2）。"""

    run_count: int = 0
    p95_latency_ms: float = 0.0  # 本地检索耗时 P95，目标 ≤ 100ms
    avg_input_tokens: float = 0.0
    avg_memory_tokens: float = 0.0
    avg_output_tokens: float = 0.0


class EvaluationReport(BaseModel):
    """一次评测的汇总报告（规格 §10.2 / §10.3 三组对照）。"""

    mode: RunMode
    classification: ClassificationMetrics = Field(default_factory=ClassificationMetrics)
    memory: MemoryMetrics = Field(default_factory=MemoryMetrics)
    cost: CostMetrics = Field(default_factory=CostMetrics)
    same_type_error_reduction: float | None = None  # 同类错误下降，目标 ≥ 50%
