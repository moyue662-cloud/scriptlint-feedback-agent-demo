"""ScriptLint 的确定性文本工具。

当前解析器有意保持透明、可测：它支持常见中文短剧格式和一组明确模式，
无法确定时不编造事实。未来可用 LLM/视觉模型替换提取器，审计契约保持不变。
"""
from __future__ import annotations

import re

from schemas.scriptlint import (
    ScriptAuditTask,
    ScriptFact,
    ScriptFeedbackEvent,
    ScriptPlanStep,
    ScriptRule,
    ScriptRuleEffect,
    ScriptRuleSeverity,
    ScriptRuleStatus,
    ScriptRuleType,
)


_EPISODE_RANGE_RE = re.compile(r"第?\s*(\d+)\s*(?:到|至|-|—|~|～)\s*第?\s*(\d+)\s*集")
_SINGLE_EPISODE_RE = re.compile(r"第\s*(\d+)\s*集")
_KNOWN_SUBJECTS = ("女主", "男主", "女二", "男二", "反派")
_FORBID_WORDS = ("不能", "不得", "禁止", "不要", "不可以", "不可")
_REQUIRE_WORDS = ("必须", "需要", "应当", "务必")
_PROPS = ("戒指", "账本", "钥匙", "手机", "项链", "U盘", "文件", "药瓶")


def plan_script_audit() -> list[ScriptPlanStep]:
    return [
        ScriptPlanStep(id="step_1", tool_name="retrieve_script_rules", purpose="检索当前项目已确认的反馈记忆"),
        ScriptPlanStep(id="step_2", tool_name="extract_script_facts", purpose="提取人物、动作、外观、知情、情绪和道具事实"),
        ScriptPlanStep(id="step_3", tool_name="audit_script_rules", purpose="执行规则违例、规则互斥和前后事实一致性检查"),
        ScriptPlanStep(id="step_4", tool_name="present_audit_result", purpose="汇总记忆来源、原文证据和修复方向"),
    ]


def plan_feedback_learning() -> list[ScriptPlanStep]:
    return [
        ScriptPlanStep(id="feedback_1", tool_name="record_script_feedback", purpose="保存纠正原文与原结果"),
        ScriptPlanStep(id="feedback_2", tool_name="propose_script_rule", purpose="将每条明确改稿意见形式化为候选规则"),
        ScriptPlanStep(id="feedback_3", tool_name="store_rule_candidate", purpose="保存候选规则但不允许参与审计"),
        ScriptPlanStep(id="feedback_4", tool_name="await_user_confirmation", purpose="等待用户逐条确认后再激活记忆"),
    ]


def _speaker(line: str) -> str | None:
    known = next((name for name in _KNOWN_SUBJECTS if name in line), None)
    if known:
        return known
    match = re.match(r"\s*([\u4e00-\u9fffA-Za-z0-9·]{1,12})\s*[：:]", line)
    if match:
        name = match.group(1)
        if name in {"场景", "内景", "外景", "时间", "地点", "镜头", "转场"}:
            return None
        return name
    return None


def _feedback_subject(text: str) -> str | None:
    known = next((name for name in _KNOWN_SUBJECTS if name in text), None)
    if known:
        return known
    match = re.match(
        r"\s*([\u4e00-\u9fffA-Za-z0-9·]{2,10})(?=在|的|第|左手|右手|左腿|右腿|不知道|不能|不得|必须)",
        text,
    )
    return match.group(1) if match else None


def extract_script_facts(task: ScriptAuditTask) -> list[ScriptFact]:
    """从用户剧本文本提取可审计事实，保留原文和行号。"""
    facts: list[ScriptFact] = []
    raw_lines = task.script_text.splitlines()
    recent_context: list[str] = []
    reserved = {"场景", "内景", "外景", "时间", "地点", "镜头", "转场"}
    discovered_cast = list(_KNOWN_SUBJECTS)
    for raw in raw_lines:
        match = re.match(r"\s*([\u4e00-\u9fffA-Za-z0-9·]{1,12})\s*[：:]", raw)
        if match and match.group(1) not in reserved and match.group(1) not in discovered_cast:
            discovered_cast.append(match.group(1))

    def add(line_no: int, line: str, subject: str, action: str, statement: str, *, object: str | None = None, value: str | None = None) -> None:
        serial = len(facts) + 1
        facts.append(
            ScriptFact(
                id=f"fact_{task.id}_{serial:03d}",
                project_id=task.project_id,
                episode=task.episode,
                scene_id=f"scene_{task.episode}_{line_no:03d}",
                subject=subject,
                action=action,
                statement=statement,
                evidence_id=f"evidence_{task.id}_{serial:03d}",
                evidence_excerpt=line,
                line_number=line_no,
                object=object,
                value=value,
            )
        )

    for line_no, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line:
            continue
        subject = next((name for name in discovered_cast if name in line), None) or _speaker(line)
        context = " ".join(recent_context[-4:] + [line])

        if subject and ("继承人" in line or "真实身份" in line) and any(
            word in line for word in ("知道", "得知", "原来", "发现", "认出", "就是")
        ):
            add(line_no, line, subject, "identity_reveal", f"{subject}获知或说破关键身份")

        if subject:
            if "：" in line or ":" in line:
                dialogue = re.split(r"[：:]", line, maxsplit=1)[1].strip()
                if dialogue:
                    add(line_no, line, subject, "speak_dialogue", f"{subject}说出指定台词", value=dialogue)

            for side in ("左手", "右手"):
                if side in line and any(word in line for word in ("提", "抬", "抓", "拿", "挥", "推", "举", "抱")):
                    add(line_no, line, subject, f"use_{side}", f"{subject}使用{side}完成负重或发力动作", value=side)
            if any(part in line for part in ("腿骨折", "腿受伤", "断腿")) and any(word in line for word in ("跑", "站起", "冲", "跳")):
                add(line_no, line, subject, "move_with_injured_leg", f"{subject}在腿部受伤设定下完成高强度移动")

            for side in ("左脸", "右脸"):
                if side in line and any(word in line for word in ("伤", "疤", "血", "创可贴")):
                    add(line_no, line, subject, f"appearance_{side}_wound", f"{subject}的面部伤痕位于{side}", value=side)

            if any(obj in line for obj in ("账本", "秘密", "证据", "钥匙")) and any(
                phrase in line for phrase in ("在城", "在仓库", "在抽屉", "藏在", "放在", "就在")
            ):
                add(line_no, line, subject, "reveal_secret_location", f"{subject}说出关键物品或秘密的位置")

            grief_context = any(word in context for word in ("葬礼", "灵堂", "去世", "死亡", "遗体", "追悼"))
            positive_emotion = any(word in line for word in ("大笑", "开心", "太好了", "兴奋", "笑出声"))
            if grief_context and positive_emotion:
                add(line_no, line, subject, "inappropriate_positive_emotion", f"{subject}在悲伤情境中表现出明显正向情绪")

            for prop in _PROPS:
                if prop not in line:
                    continue
                if any(word in line for word in ("拿出", "掏出", "戴上", "使用", "举起")):
                    add(line_no, line, subject, f"use_prop:{prop}", f"{subject}再次使用或持有{prop}", object=prop)
                if any(word in line for word in ("交给", "递给", "送给")):
                    add(line_no, line, subject, f"transfer_prop:{prop}", f"{subject}转交了{prop}", object=prop)
                if any(word in line for word in ("烧毁", "摔碎", "销毁", "丢掉", "扔进")):
                    add(line_no, line, subject, f"destroy_prop:{prop}", f"{subject}销毁或丢弃了{prop}", object=prop)

        recent_context.append(line)
    return facts


def _rule_semantics(text: str) -> tuple[ScriptRuleType, str, str] | None:
    if "继承人" in text or "真实身份" in text or ("身份" in text and "知道" in text):
        return ScriptRuleType.identity_knowledge, "identity_reveal", "身份知情时点"
    if "左手" in text and any(word in text for word in ("提", "拿", "发力", "使用", "动作")):
        return ScriptRuleType.physical_continuity, "use_左手", "左手动作连续性"
    if "右手" in text and any(word in text for word in ("提", "拿", "发力", "使用", "动作")):
        return ScriptRuleType.physical_continuity, "use_右手", "右手动作连续性"
    if any(word in text for word in ("腿骨折", "腿受伤", "断腿")) and any(word in text for word in ("跑", "站", "冲", "跳")):
        return ScriptRuleType.physical_continuity, "move_with_injured_leg", "腿部动作连续性"
    if "不能写成右脸" in text or "不得写成右脸" in text:
        return ScriptRuleType.appearance_continuity, "appearance_右脸_wound", "面部伤痕位置"
    if "不能写成左脸" in text or "不得写成左脸" in text:
        return ScriptRuleType.appearance_continuity, "appearance_左脸_wound", "面部伤痕位置"
    if any(word in text for word in ("不知道", "不知情")) and any(word in text for word in ("位置", "在哪", "账本", "秘密", "证据")):
        return ScriptRuleType.knowledge_continuity, "reveal_secret_location", "人物知情边界"
    if any(word in text for word in ("葬礼", "灵堂", "去世", "死亡", "追悼")) and any(word in text for word in ("笑", "开心", "兴奋")):
        return ScriptRuleType.emotion_context, "inappropriate_positive_emotion", "情绪与情境一致性"
    prop = next((item for item in _PROPS if item in text), None)
    if prop and any(word in text for word in ("不能再拿", "不得再拿", "不能使用", "不能戴", "不能拿出")):
        return ScriptRuleType.prop_continuity, f"use_prop:{prop}", f"{prop}持有连续性"
    quoted = re.search(r"[“\"]([^”\"]{2,50})[”\"]", text)
    if quoted and any(word in text for word in ("台词", "说", "讲")):
        return ScriptRuleType.dialogue, "speak_dialogue", "具体台词归属"
    return None


def propose_script_rules(feedback: ScriptFeedbackEvent) -> list[ScriptRule]:
    """将多行/分号分隔的明确意见拆成多条候选规则。"""
    segments = [part.strip(" -•\t") for part in re.split(r"[\n；;]+", feedback.user_text) if part.strip(" -•\t")]
    rules: list[ScriptRule] = []
    for text in segments:
        subject = _feedback_subject(text)
        semantics = _rule_semantics(text)
        if subject is None or semantics is None:
            continue

        range_match = _EPISODE_RANGE_RE.search(text)
        single_match = _SINGLE_EPISODE_RE.search(text)
        episode_from: int | None = None
        episode_to: int | None = None
        if range_match:
            episode_from, episode_to = map(int, range_match.groups())
        elif single_match:
            episode_from = episode_to = int(single_match.group(1))

        if any(word in text for word in _FORBID_WORDS) or "不知情" in text or "不知道" in text:
            effect = ScriptRuleEffect.forbid
            severity = ScriptRuleSeverity.hard
        elif any(word in text for word in _REQUIRE_WORDS):
            effect = ScriptRuleEffect.require
            severity = ScriptRuleSeverity.hard
        elif any(word in text for word in ("尽量", "最好", "偏好")):
            effect = ScriptRuleEffect.prefer
            severity = ScriptRuleSeverity.preference
        else:
            continue

        rule_type, action, label = semantics
        confidence = min(0.78 + (0.08 if episode_from is not None else 0) + (0.06 if len(text) >= 12 else 0), 0.96)
        rules.append(
            ScriptRule(
                id=f"rule_{feedback.id}_{len(rules) + 1:02d}",
                team_id=feedback.team_id,
                project_id=feedback.project_id,
                rule_type=rule_type,
                title=f"{subject} · {label}",
                subject=subject,
                action=action,
                effect=effect,
                requirement=text,
                severity=severity,
                episode_from=episode_from,
                episode_to=episode_to,
                source_feedback_id=feedback.id,
                source_excerpt=text,
                confidence=confidence,
                status=ScriptRuleStatus.candidate,
                created_at=feedback.created_at,
            )
        )
    return rules


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 1) // 2)
