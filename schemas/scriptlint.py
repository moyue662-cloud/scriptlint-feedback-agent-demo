"""ScriptLint 第一阶段领域契约。

这些模型先与 DecisionPatch 旧契约并存，避免在演示闭环验证前破坏现有应用。
第一阶段只覆盖：用户反馈 -> 候选规则 -> 人工确认 -> 后续任务检索与审计。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ScriptRuleType(str, Enum):
    identity_knowledge = "identity_knowledge"
    knowledge_continuity = "knowledge_continuity"
    physical_continuity = "physical_continuity"
    appearance_continuity = "appearance_continuity"
    emotion_context = "emotion_context"
    prop_continuity = "prop_continuity"
    timeline = "timeline"
    character_behavior = "character_behavior"
    dialogue = "dialogue"
    production = "production"
    style = "style"


class ScriptRuleEffect(str, Enum):
    forbid = "forbid"
    require = "require"
    prefer = "prefer"


class ScriptRuleSeverity(str, Enum):
    hard = "hard"
    soft = "soft"
    preference = "preference"


class ScriptRuleStatus(str, Enum):
    candidate = "candidate"
    active = "active"
    paused = "paused"
    superseded = "superseded"
    archived = "archived"


class ScriptRule(BaseModel):
    """由一次明确反馈形成的、可审计的短剧项目规则。"""

    id: str
    team_id: str
    project_id: str
    rule_type: ScriptRuleType
    title: str
    subject: str = Field(description="规则约束的角色或对象")
    action: str = Field(description="稳定动作键，如 identity_reveal")
    effect: ScriptRuleEffect
    requirement: str
    severity: ScriptRuleSeverity = ScriptRuleSeverity.hard
    episode_from: int | None = Field(default=None, ge=1)
    episode_to: int | None = Field(default=None, ge=1)
    source_feedback_id: str | None = None
    source_excerpt: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ScriptRuleStatus = ScriptRuleStatus.candidate
    version: int = Field(default=1, ge=1)
    supersedes_id: str | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_scope_and_source(self) -> "ScriptRule":
        if (
            self.episode_from is not None
            and self.episode_to is not None
            and self.episode_from > self.episode_to
        ):
            raise ValueError("episode_from 不能大于 episode_to")
        if self.status == ScriptRuleStatus.candidate and not self.source_feedback_id:
            raise ValueError("候选规则必须保留 source_feedback_id")
        if self.source_feedback_id and not self.source_excerpt:
            raise ValueError("有反馈来源的规则必须保留 source_excerpt")
        return self

    def applies_to_episode(self, episode: int) -> bool:
        if self.episode_from is not None and episode < self.episode_from:
            return False
        if self.episode_to is not None and episode > self.episode_to:
            return False
        return True


class ScriptFact(BaseModel):
    """从剧本中提取的、带原文证据的最小事实。"""

    id: str
    project_id: str
    episode: int = Field(ge=1)
    scene_id: str
    subject: str
    action: str
    statement: str
    evidence_id: str
    evidence_excerpt: str
    line_number: int | None = Field(default=None, ge=1)
    object: str | None = None
    value: str | None = None


class RuleUseDecision(str, Enum):
    apply = "apply"
    ignore = "ignore"
    conflict = "conflict"


class FindingType(str, Enum):
    rule_violation = "rule_violation"
    rule_conflict = "rule_conflict"
    rule_drift = "rule_drift"
    fact_inconsistency = "fact_inconsistency"


class RuleUseTrace(BaseModel):
    rule_id: str
    decision: RuleUseDecision
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class AuditFinding(BaseModel):
    id: str
    finding_type: FindingType
    severity: ScriptRuleSeverity
    rule_ids: list[str] = Field(default_factory=list)
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list, max_length=3)


class ScriptAuditTask(BaseModel):
    id: str
    team_id: str
    project_id: str
    episode: int = Field(ge=1)
    title: str
    script_text: str
    version_id: str | None = None
    facts: list[ScriptFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _facts_belong_to_task(self) -> "ScriptAuditTask":
        for fact in self.facts:
            if fact.project_id != self.project_id or fact.episode != self.episode:
                raise ValueError("剧本事实必须属于当前项目和集数")
        return self


class ScriptSourceKind(str, Enum):
    pasted = "pasted"
    uploaded = "uploaded"
    demo = "demo"


class ScriptVersion(BaseModel):
    """用户自有剧本的一次可复用版本。"""

    id: str
    team_id: str
    project_id: str
    project_name: str
    version_label: str
    episode: int = Field(ge=1)
    title: str
    script_text: str = Field(min_length=1)
    source_kind: ScriptSourceKind
    source_name: str | None = None
    content_hash: str
    parent_version_id: str | None = None
    created_at: datetime


class ScriptAuditMetrics(BaseModel):
    memory_hit_count: int = Field(ge=0)
    memory_applied_count: int = Field(ge=0)
    memory_ignored_count: int = Field(ge=0)
    memory_conflict_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)


class ScriptAuditResult(BaseModel):
    task_id: str
    traces: list[RuleUseTrace] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)
    metrics: ScriptAuditMetrics


class ScriptFeedbackEvent(BaseModel):
    """一次可追溯的剧本审计纠正。"""

    id: str
    team_id: str
    project_id: str
    original_result: str
    user_text: str
    created_at: datetime


class ScriptPlanStepStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    skipped = "skipped"


class ScriptPlanStep(BaseModel):
    id: str
    tool_name: str
    purpose: str
    status: ScriptPlanStepStatus = ScriptPlanStepStatus.pending


class ScriptToolStatus(str, Enum):
    succeeded = "succeeded"
    failed = "failed"


class ScriptToolTrace(BaseModel):
    sequence: int = Field(ge=1)
    tool_name: str
    status: ScriptToolStatus
    input_summary: str
    output_summary: str
    duration_ms: float = Field(ge=0)


class ScriptAgentMetrics(BaseModel):
    latency_ms: float = Field(ge=0)
    model_call_count: int = Field(default=0, ge=0)
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_memory_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    memory_hit_count: int = Field(default=0, ge=0)
    memory_applied_count: int = Field(default=0, ge=0)


class ScriptAgentResult(BaseModel):
    run_id: str
    task: ScriptAuditTask
    retrieved_rules: list[ScriptRule]
    plan: list[ScriptPlanStep]
    tool_traces: list[ScriptToolTrace]
    audit: ScriptAuditResult
    metrics: ScriptAgentMetrics


class ScriptFeedbackResult(BaseModel):
    feedback: ScriptFeedbackEvent
    candidates: list[ScriptRule]
    plan: list[ScriptPlanStep]
    tool_traces: list[ScriptToolTrace]


class ValidationRole(str, Enum):
    screenwriter = "screenwriter"
    student_creator = "student_creator"
    producer_editor = "producer_editor"
    other = "other"


class ValidationJudgment(str, Enum):
    correct = "correct"
    partly_correct = "partly_correct"
    incorrect = "incorrect"


class ScriptUserValidation(BaseModel):
    """少量真实用户验证记录；禁止存储姓名、联系方式和原始剧本。"""

    id: str
    team_id: str
    project_id: str
    participant_code: str = Field(min_length=2, max_length=16)
    role: ValidationRole
    scenario_id: str = "identity_reveal_demo"
    completed_feedback_loop: bool
    rule_judgment: ValidationJudgment
    explanation_clarity: int = Field(ge=1, le=5)
    trace_trust: int = Field(ge=1, le=5)
    would_use: bool
    duration_seconds: int | None = Field(default=None, ge=1, le=1800)
    comment: str | None = Field(default=None, max_length=500)
    consent: bool
    created_at: datetime

    @field_validator("participant_code")
    @classmethod
    def _anonymous_code_only(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("participant_code 只能包含字母、数字、下划线或短横线")
        return normalized

    @model_validator(mode="after")
    def _require_consent(self) -> "ScriptUserValidation":
        if not self.consent:
            raise ValueError("未同意匿名记录时不得保存验证结果")
        return self


class ScriptValidationSummary(BaseModel):
    participant_count: int = Field(ge=0)
    completion_rate: float = Field(ge=0, le=1)
    correct_rate: float = Field(ge=0, le=1)
    avg_explanation_clarity: float = Field(ge=0, le=5)
    avg_trace_trust: float = Field(ge=0, le=5)
    would_use_rate: float = Field(ge=0, le=1)
    ready_for_directional_claim: bool = False


class DemoFeedback(BaseModel):
    id: str
    speaker: str
    original_result: str
    user_text: str


class DemoCase(BaseModel):
    id: str
    description: str
    task: ScriptAuditTask
    rule_ids: list[str] = Field(default_factory=list)
    expected_applied_rule_ids: list[str] = Field(default_factory=list)
    expected_ignored_rule_ids: list[str] = Field(default_factory=list)
    expected_finding_types: list[FindingType] = Field(default_factory=list)


class ScriptLintDemoFixture(BaseModel):
    schema_version: str
    data_label: str
    team_id: str
    project_id: str
    project_name: str
    feedback: DemoFeedback
    candidate_rules: list[ScriptRule]
    confirmed_rules: list[ScriptRule]
    cases: list[DemoCase]

    @model_validator(mode="after")
    def _validate_references(self) -> "ScriptLintDemoFixture":
        all_rules = {rule.id: rule for rule in self.candidate_rules + self.confirmed_rules}
        for case in self.cases:
            if case.task.team_id != self.team_id or case.task.project_id != self.project_id:
                raise ValueError("演示任务必须属于演示团队和项目")
            missing = set(case.rule_ids) - set(all_rules)
            if missing:
                raise ValueError(f"演示任务引用不存在的规则: {sorted(missing)}")
        return self
