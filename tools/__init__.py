"""P0 工具集（规格 7.2）。

每个工具拥有明确的输入输出契约：
- normalize_chat    原始文本 -> Message 列表 + 解析警告（确定性）
- extract_decisions 消息 + 候选记忆 -> 决策对象列表（调模型）
- detect_conflicts  决策对象 + 历史决定 -> 冲突与取代关系（混合）
- build_receipt     决策对象 + 证据 -> 前端展示结构（确定性）
- propose_memory    修改前/后 + 反馈 -> 候选记忆（调模型）
- record_metrics    运行统计 -> agent_run 记录（确定性）
"""
from __future__ import annotations

from .build_receipt import build_receipt, ReceiptCard, ReceiptBundle
from .detect_conflicts import detect_conflicts, ConflictReport, ConflictItem
from .extract_decisions import extract_decisions
from .normalize_chat import normalize_chat
from .propose_memory import propose_memory
from .record_metrics import record_metrics
from .scriptlint_tools import (
    estimate_tokens,
    extract_script_facts,
    plan_feedback_learning,
    plan_script_audit,
    propose_script_rules,
)

__all__ = [
    "normalize_chat",
    "extract_decisions",
    "detect_conflicts",
    "detect_conflicts",
    "build_receipt",
    "propose_memory",
    "record_metrics",
    "ReceiptCard",
    "ReceiptBundle",
    "ConflictReport",
    "ConflictItem",
    "plan_script_audit",
    "plan_feedback_learning",
    "extract_script_facts",
    "propose_script_rules",
    "estimate_tokens",
]
