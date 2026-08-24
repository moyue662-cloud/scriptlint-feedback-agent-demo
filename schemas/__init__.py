"""DecisionPatch 信息模型（Pydantic v2）。

本包是规格第 5 节"信息模型"的单一事实来源。前端（Kimi）只依赖这里的
Pydantic / JSON 契约，后端不得在未通知的情况下改字段（规格 16.2）。

模块划分：
- message.py    消息、聊天记录、解析警告、数据来源标签
- decision.py   决策对象 DecisionRecord 及其类型 / 状态枚举
- memory.py     记忆对象 MemoryRule、适用性判断 ApplicabilityJudgment
- feedback.py   反馈事件 FeedbackEvent、候选记忆 MemoryCandidate
- metrics.py    运行指标 AgentRun、三组对照模式 RunMode
"""
from __future__ import annotations

from .decision import (
    CreatedBy,
    DecisionRecord,
    DecisionStatus,
    DecisionType,
)
from .feedback import FeedbackEvent, MemoryCandidate
from .memory import (
    ApplicabilityDecision,
    ApplicabilityJudgment,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    RuleType,
)
from .message import ChatLog, DataSourceLabel, Message, ParseWarning
from .metrics import AgentRun, RunMode
from .scriptlint import (
    AuditFinding,
    DemoCase,
    DemoFeedback,
    FindingType,
    RuleUseDecision,
    RuleUseTrace,
    ScriptAuditMetrics,
    ScriptAuditResult,
    ScriptAuditTask,
    ScriptAgentMetrics,
    ScriptAgentResult,
    ScriptFact,
    ScriptSourceKind,
    ScriptVersion,
    ScriptFeedbackEvent,
    ScriptFeedbackResult,
    ScriptLintDemoFixture,
    ScriptPlanStep,
    ScriptPlanStepStatus,
    ScriptRule,
    ScriptRuleEffect,
    ScriptRuleSeverity,
    ScriptRuleStatus,
    ScriptRuleType,
    ScriptToolStatus,
    ScriptToolTrace,
    ScriptUserValidation,
    ScriptValidationSummary,
    ValidationJudgment,
    ValidationRole,
)
from .multimodal import (
    AudioQualityMetrics,
    AudioReviewReport,
    DialogueAlignment,
    DialogueMatchStatus,
    EvidenceLocator,
    IgnoredScriptLine,
    ReviewAsset,
    ReviewEvidence,
    ReviewModality,
    ReviewObservation,
    ScriptDialogueLine,
    ScriptDialogueParseResult,
    SubtitleObservation,
    TranscriptSegment,
    VisualIssue,
    VisualIssueType,
    VisualQualityReport,
)
from .evaluation import (
    ClassifiedItem,
    ClassificationMetrics,
    MemoryApplicationRecord,
    MemoryMetrics,
    CostMetrics,
    EvaluationReport,
)

__all__ = [
    # message
    "Message",
    "ChatLog",
    "ParseWarning",
    "DataSourceLabel",
    # decision
    "DecisionRecord",
    "DecisionType",
    "DecisionStatus",
    "CreatedBy",
    # memory
    "MemoryRule",
    "RuleType",
    "MemoryStatus",
    "MemoryScope",
    "ApplicabilityJudgment",
    "ApplicabilityDecision",
    # feedback
    "FeedbackEvent",
    "MemoryCandidate",
    # metrics
    "AgentRun",
    "RunMode",
    # scriptlint
    "ScriptRule",
    "ScriptRuleType",
    "ScriptRuleEffect",
    "ScriptRuleSeverity",
    "ScriptRuleStatus",
    "ScriptFact",
    "ScriptSourceKind",
    "ScriptVersion",
    "ReviewModality",
    "EvidenceLocator",
    "ReviewAsset",
    "ReviewEvidence",
    "ReviewObservation",
    "TranscriptSegment",
    "ScriptDialogueLine",
    "IgnoredScriptLine",
    "ScriptDialogueParseResult",
    "SubtitleObservation",
    "DialogueMatchStatus",
    "DialogueAlignment",
    "AudioQualityMetrics",
    "AudioReviewReport",
    "VisualIssue",
    "VisualIssueType",
    "VisualQualityReport",
    "RuleUseDecision",
    "RuleUseTrace",
    "FindingType",
    "AuditFinding",
    "ScriptAuditTask",
    "ScriptAuditMetrics",
    "ScriptAuditResult",
    "ScriptFeedbackEvent",
    "ScriptPlanStepStatus",
    "ScriptPlanStep",
    "ScriptToolStatus",
    "ScriptToolTrace",
    "ScriptAgentMetrics",
    "ScriptAgentResult",
    "ScriptFeedbackResult",
    "ValidationRole",
    "ValidationJudgment",
    "ScriptUserValidation",
    "ScriptValidationSummary",
    "DemoFeedback",
    "DemoCase",
    "ScriptLintDemoFixture",
]
