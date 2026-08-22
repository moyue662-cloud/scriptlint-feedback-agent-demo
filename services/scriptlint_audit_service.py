"""ScriptLint 第一阶段确定性审计服务。

LLM 在后续阶段负责从自然语言提取 ScriptRule 与 ScriptFact；本服务负责
作用域、规则互斥和事实命中等可重复判断，使离线 Demo 稳定可测。
"""
from __future__ import annotations

from itertools import combinations
import re

from schemas.scriptlint import (
    AuditFinding,
    FindingType,
    RuleUseDecision,
    RuleUseTrace,
    ScriptAuditMetrics,
    ScriptAuditResult,
    ScriptAuditTask,
    ScriptRule,
    ScriptRuleEffect,
    ScriptRuleSeverity,
    ScriptRuleStatus,
)


class ScriptLintAuditService:
    def audit(
        self,
        *,
        task: ScriptAuditTask,
        rules: list[ScriptRule],
    ) -> ScriptAuditResult:
        traces: list[RuleUseTrace] = []
        findings: list[AuditFinding] = []
        relevant: list[ScriptRule] = []

        for rule in rules:
            if rule.status != ScriptRuleStatus.active:
                continue
            if rule.team_id != task.team_id or rule.project_id != task.project_id:
                continue
            if not rule.applies_to_episode(task.episode):
                traces.append(
                    RuleUseTrace(
                        rule_id=rule.id,
                        decision=RuleUseDecision.ignore,
                        reason=f"当前为第{task.episode}集，超出规则适用范围",
                    )
                )
                continue
            relevant.append(rule)

        conflicting_ids = self._detect_rule_conflicts(relevant, findings)
        self._detect_fact_inconsistencies(task, findings)

        for rule in relevant:
            if rule.id in conflicting_ids:
                traces.append(
                    RuleUseTrace(
                        rule_id=rule.id,
                        decision=RuleUseDecision.conflict,
                        reason="存在同对象、同动作、作用域重叠但效果相反的已生效规则",
                    )
                )
                continue

            matched_facts = [
                fact
                for fact in task.facts
                if fact.subject == rule.subject and fact.action == rule.action
            ]
            if rule.rule_type.value == "dialogue":
                quoted = re.search(r"[“\"]([^”\"]{2,50})[”\"]", rule.requirement)
                if quoted:
                    expected_line = quoted.group(1)
                    matched_facts = [
                        fact for fact in matched_facts if expected_line in (fact.value or "")
                    ]
            traces.append(
                RuleUseTrace(
                    rule_id=rule.id,
                    decision=RuleUseDecision.apply,
                    reason="项目、集数、对象和动作均符合规则作用域",
                    evidence_ids=[fact.evidence_id for fact in matched_facts],
                )
            )

            if rule.effect == ScriptRuleEffect.forbid and matched_facts:
                fact = matched_facts[0]
                findings.append(
                    AuditFinding(
                        id=f"finding_{task.id}_{rule.id}",
                        finding_type=FindingType.rule_violation,
                        severity=rule.severity,
                        rule_ids=[rule.id],
                        reason=fact.statement,
                        evidence_ids=[fact.evidence_id],
                        suggestions=self._suggestions_for(rule),
                    )
                )
            elif rule.effect == ScriptRuleEffect.require and not matched_facts:
                findings.append(
                    AuditFinding(
                        id=f"finding_{task.id}_{rule.id}",
                        finding_type=FindingType.rule_violation,
                        severity=rule.severity,
                        rule_ids=[rule.id],
                        reason=f"第{task.episode}集未出现规则要求的动作：{rule.requirement}",
                        suggestions=["补充对应剧情动作", "调整规则适用集数", "暂停该规则并记录原因"],
                    )
                )

        metrics = ScriptAuditMetrics(
            # 只有通过团队/项目隔离的规则才算一次有效检索命中；跨项目规则
            # 即便误传给审计层，也不能进入指标或调用轨迹。
            memory_hit_count=len(traces),
            memory_applied_count=sum(t.decision == RuleUseDecision.apply for t in traces),
            memory_ignored_count=sum(t.decision == RuleUseDecision.ignore for t in traces),
            memory_conflict_count=sum(t.decision == RuleUseDecision.conflict for t in traces),
            finding_count=len(findings),
        )
        return ScriptAuditResult(
            task_id=task.id,
            traces=traces,
            findings=findings,
            metrics=metrics,
        )

    @staticmethod
    def _suggestions_for(rule: ScriptRule) -> list[str]:
        by_type = {
            "identity_knowledge": ["改为只暗示身份，不让该角色明确知情", "将揭示推迟到规则失效后的集数"],
            "knowledge_continuity": ["删除该角色不应掌握的信息", "补充可信的信息获取过程并提交规则变更"],
            "physical_continuity": ["改用未受伤部位或让其他角色完成动作", "补充恢复、治疗或辅助动作的剧情依据"],
            "appearance_continuity": ["统一伤痕、服装或外形所在位置", "若设定改变，补充变化事件并更新规则"],
            "emotion_context": ["调整表情、语气或动作以符合当前情境", "补充反常情绪的角色动机"],
            "prop_continuity": ["改用当前仍由角色持有的道具", "补充道具重新取得或替换的过程"],
            "dialogue": ["将台词转交给正确角色", "调整措辞以符合角色身份和知情范围"],
        }
        suggestions = list(by_type.get(rule.rule_type.value, ["修改对应剧情事实", "调整规则作用域并说明原因"]))
        suggestions.append("若本集确需例外，提交新的改稿意见并人工确认")
        return suggestions[:3]

    @staticmethod
    def _detect_fact_inconsistencies(
        task: ScriptAuditTask, findings: list[AuditFinding]
    ) -> None:
        """发现不依赖用户规则也可确定的局部连续性矛盾。"""
        by_subject: dict[str, list] = {}
        for fact in task.facts:
            by_subject.setdefault(fact.subject, []).append(fact)

        for subject, facts in by_subject.items():
            left = [fact for fact in facts if fact.action == "appearance_左脸_wound"]
            right = [fact for fact in facts if fact.action == "appearance_右脸_wound"]
            if left and right:
                findings.append(
                    AuditFinding(
                        id=f"fact_conflict_{task.id}_{subject}_face",
                        finding_type=FindingType.fact_inconsistency,
                        severity=ScriptRuleSeverity.hard,
                        reason=f"{subject}的面部伤痕在同一版本中同时被写为左脸和右脸",
                        evidence_ids=[left[0].evidence_id, right[0].evidence_id],
                        suggestions=["统一伤痕所在侧", "若伤口发生变化，补充明确的转场或新事件"],
                    )
                )

        destroyed: dict[str, object] = {}
        ordered = sorted(task.facts, key=lambda fact: fact.line_number or 0)
        for fact in ordered:
            if fact.object and fact.action.startswith("destroy_prop:"):
                destroyed[fact.object] = fact
            elif fact.object and fact.action.startswith("use_prop:") and fact.object in destroyed:
                prior = destroyed[fact.object]
                findings.append(
                    AuditFinding(
                        id=f"fact_conflict_{task.id}_{fact.object}_{fact.id}",
                        finding_type=FindingType.fact_inconsistency,
                        severity=ScriptRuleSeverity.hard,
                        reason=f"{fact.object}已被销毁或丢弃，后文却再次被使用",
                        evidence_ids=[prior.evidence_id, fact.evidence_id],
                        suggestions=["删除后续道具使用", "补充同款替代品或道具被找回的剧情依据"],
                    )
                )

    @staticmethod
    def _detect_rule_conflicts(
        rules: list[ScriptRule], findings: list[AuditFinding]
    ) -> set[str]:
        conflicting: set[str] = set()
        for left, right in combinations(rules, 2):
            same_target = left.subject == right.subject and left.action == right.action
            left_from, left_to = left.episode_from or 1, left.episode_to or 10**9
            right_from, right_to = right.episode_from or 1, right.episode_to or 10**9
            overlaps = max(left_from, right_from) <= min(left_to, right_to)
            opposite = {left.effect, right.effect} == {
                ScriptRuleEffect.forbid,
                ScriptRuleEffect.require,
            }
            if not (same_target and opposite and overlaps):
                continue
            conflicting.update([left.id, right.id])
            findings.append(
                AuditFinding(
                    id=f"conflict_{left.id}_{right.id}",
                    finding_type=FindingType.rule_conflict,
                    severity=ScriptRuleSeverity.hard,
                    rule_ids=[left.id, right.id],
                    reason="两条已确认规则要求同一角色在同一作用域内同时禁止和必须执行同一动作",
                    suggestions=[
                        "选择一条规则覆盖另一条",
                        "缩小其中一条规则的集数范围",
                        "保留为待确认冲突，暂不定稿",
                    ],
                )
            )
        return conflicting
