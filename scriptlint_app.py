"""ScriptLint Streamlit 演示工作台。"""
from __future__ import annotations

import html
import hashlib
import inspect
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from config import PROJECT_ROOT
from eval.run_scriptlint_eval import run_scriptlint_eval
from repositories import SQLiteRepository
from schemas.scriptlint import (
    RuleUseDecision,
    ScriptAgentResult,
    ScriptAuditTask,
    ScriptFeedbackResult,
    ScriptSourceKind,
    ScriptRuleStatus,
    ScriptUserValidation,
    ScriptVersion,
    ValidationJudgment,
    ValidationRole,
)
from services.scriptlint_agent import ScriptLintAgent
from services.script_validation_service import ScriptValidationService


CST = timezone(timedelta(hours=8))
TEAM_ID = "team_scriptlint_demo"
DEFAULT_PROJECT_ID = "project_my_short_drama"
DEMO_SCRIPT = """第3集 内景 灵堂 日
女主左手缠着厚厚的绷带，却用左手提起沉重的箱子。
男主左脸有一道新伤。
女主：账本就在城南仓库。
女主开心地大笑：太好了！
反派把戒指扔进火里烧毁。
男主从口袋拿出戒指。
男主右脸的伤口渗出血迹。"""
DEMO_FOLLOWUP = """第4集 内景 仓库 夜
女主用左手举起铁箱砸向门锁。
女主：账本就在城南仓库最里面。
男主右脸贴着创可贴，拿出那枚戒指。"""
DEMO_FEEDBACK = """女主左手受伤，第1到4集不能用左手提重物；
女主不知道账本位置，不能说出账本在哪；
男主伤口在左脸，不能写成右脸；
葬礼场景女主不能开心大笑；
戒指已经销毁，男主不能再拿出戒指"""

RULE_TYPE_LABELS = {
    "identity_knowledge": "身份知情",
    "knowledge_continuity": "知情边界",
    "physical_continuity": "动作能力",
    "appearance_continuity": "外观连续",
    "emotion_context": "情绪情境",
    "prop_continuity": "道具连续",
    "timeline": "时间线",
    "character_behavior": "人物行为",
    "dialogue": "台词归属",
    "production": "制作约束",
    "style": "风格偏好",
}


def _stretch(func) -> dict:
    if "width" in inspect.signature(func).parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


def _now() -> datetime:
    return datetime.now(CST)


def _project_id() -> str:
    raw = st.session_state.get("project_code", DEFAULT_PROJECT_ID).strip()
    safe = "".join(char if char.isalnum() or char in "_-" else "_" for char in raw)
    return safe or DEFAULT_PROJECT_ID


def _project_name() -> str:
    return st.session_state.get("project_name", "我的短剧项目").strip() or "我的短剧项目"


def _decode_upload(uploaded) -> str:
    data = uploaded.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码无法识别，请另存为 UTF-8 文本后重试。")


def _save_version(repo: SQLiteRepository, *, source_kind: ScriptSourceKind, source_name: str | None = None) -> ScriptVersion:
    text = st.session_state.get("script_input", "").strip()
    versions = repo.list_script_versions(team_id=TEAM_ID, project_id=_project_id())
    version = ScriptVersion(
        id=f"version_{uuid.uuid4().hex[:10]}",
        team_id=TEAM_ID,
        project_id=_project_id(),
        project_name=_project_name(),
        version_label=st.session_state.get("version_label", f"V{len(versions) + 1}").strip() or f"V{len(versions) + 1}",
        episode=int(st.session_state.get("episode_input", 1)),
        title=st.session_state.get("script_title", "本集审计").strip() or "本集审计",
        script_text=text,
        source_kind=source_kind,
        source_name=source_name,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        parent_version_id=versions[0].id if versions else None,
        created_at=_now(),
    )
    repo.create_team(id=TEAM_ID, name="ScriptLint 本地用户", created_at=version.created_at)
    repo.create_project(id=version.project_id, team_id=TEAM_ID, name=version.project_name, created_at=version.created_at)
    repo.insert_script_version(version)
    return version


@st.cache_resource(show_spinner=False)
def _runtime(db_path: str):
    repo = SQLiteRepository(db_path)
    repo.init()
    return repo, ScriptLintAgent(repo)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#172032; --muted:#778196; --line:#e7e9ef; --paper:#f6f5f2; --red:#e9584f; --purple:#6f5de7; --green:#20866f; }
        .stApp { background:linear-gradient(180deg,#f7f6f3 0,#f4f5f8 100%); color:var(--ink); }
        [data-testid="stHeader"] { background:rgba(247,246,243,.88); }
        .block-container { max-width:1380px; padding-top:2.2rem; padding-bottom:5rem; }
        h1,h2,h3,h4,p,div,span,button,input,textarea { font-family:Inter,"Microsoft YaHei",sans-serif; }
        h1 { letter-spacing:-.055em; font-weight:850; }
        code,.mono { font-family:"Cascadia Code",Consolas,monospace!important; }
        [data-testid="stSidebar"] { background:#171b27; border-right:0; }
        [data-testid="stSidebar"] * { color:#e9ebf2; }
        [data-testid="stSidebar"] .stCaption { color:#9299ab; }
        section[data-testid="stSidebar"] .stButton>button { background:#252a39!important; border-color:#343b4d!important; color:#f5f6fa!important; }
        .brand { display:flex;align-items:center;gap:11px;margin-bottom:24px; }
        .brand-mark { width:39px;height:39px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(135deg,#ff746b,#cf3f5f);color:white;font-weight:900;box-shadow:0 9px 25px rgba(221,66,83,.3); }
        .brand-title { font-size:18px;font-weight:850;color:#fff;line-height:1; }
        .brand-sub { color:#8f97aa;font-size:10px;letter-spacing:.14em;margin-top:5px;text-transform:uppercase; }
        .hero { display:flex;justify-content:space-between;gap:30px;align-items:flex-start;margin-bottom:21px; }
        .hero h1 { margin:0;font-size:46px;color:#171d2b; }
        .hero p { max-width:720px;color:#6f788b;line-height:1.7;margin:10px 0 0;font-size:15px; }
        .eyebrow { font:700 11px "Cascadia Code",monospace;color:#d14b56;letter-spacing:.13em;text-transform:uppercase;margin-bottom:7px; }
        .mode-pill { display:inline-flex;gap:8px;align-items:center;border:1px solid #ded9f8;background:#f4f1ff;color:#6151c7;border-radius:999px;padding:8px 12px;font-size:11px;font-weight:800;white-space:nowrap; }
        .mode-dot { width:7px;height:7px;border-radius:50%;background:#7161e7;box-shadow:0 0 0 4px rgba(113,97,231,.13); }
        .flow { display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:0 0 24px; }
        .flow-item { background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 14px;color:#838b9b;font-size:12px;font-weight:750; }
        .flow-item.active { border-color:#dfc2c5;background:#fff8f7;color:#b6404a; }
        .flow-n { font:700 10px "Cascadia Code",monospace;margin-right:7px;color:#a8aebb; }
        .flow-item.active .flow-n { color:#d14b56; }
        .panel { background:#fff;border:1px solid var(--line);border-radius:19px;padding:22px;box-shadow:0 10px 32px rgba(35,39,53,.04); }
        .panel-title { font-size:18px;font-weight:850;color:#1b2232; }
        .panel-note { color:#81899a;font-size:12px;line-height:1.6;margin-top:4px; }
        .section-label { margin:24px 0 10px;color:#9299a8;font:750 10px "Cascadia Code",monospace;letter-spacing:.13em;text-transform:uppercase; }
        .finding { border:1px solid #f0d4d1;border-left:4px solid var(--red);background:#fffafa;border-radius:14px;padding:16px;margin:10px 0; }
        .finding-title { color:#b83d39;font-size:14px;font-weight:850; }
        .trace-quote { background:#f6f7fa;border-radius:10px;padding:11px 13px;margin-top:9px;color:#515b6d;font-size:12px;line-height:1.6;border-left:2px solid #cbd0da; }
        .source-quote { background:#f4f1ff;border-radius:10px;padding:11px 13px;margin-top:9px;color:#5e558a;font-size:12px;line-height:1.6;border-left:2px solid #8c7dea; }
        .rule-card { border:1px solid #e4e0f8;background:#fbfaff;border-radius:14px;padding:15px;margin:9px 0; }
        .rule-title { font-size:14px;font-weight:850;color:#38305f; }
        .rule-meta { color:#81799f;font-size:11px;margin-top:6px;line-height:1.6; }
        .empty { text-align:center;border:1px dashed #d8dbe3;border-radius:16px;padding:40px 20px;color:#858d9d;background:#fbfbfc; }
        .status-chip { display:inline-block;border-radius:7px;padding:4px 8px;font:700 10px "Cascadia Code",monospace; }
        .chip-active { background:#e5f5f0;color:#1e7865; }
        .chip-candidate { background:#fff1dd;color:#aa671e; }
        .chip-ignore { background:#eef0f4;color:#687184; }
        .chip-conflict { background:#fee8e6;color:#ba403a; }
        div[data-testid="stMetric"] { background:#fff;border:1px solid var(--line);border-radius:15px;padding:13px 15px; }
        div[data-testid="stMetricLabel"] { color:#7e8798; }
        div[data-testid="stMetricValue"] { color:#1b2232; }
        .stButton>button { border-radius:10px;font-weight:780;min-height:2.45rem; }
        .stButton>button[kind="primary"] { background:#d94c55!important;border-color:#d94c55!important;color:white!important; }
        .stTextArea textarea,.stTextInput input { border-radius:11px!important;border-color:#dfe2e9!important;background:#fcfcfd!important; }
        .stTabs [data-baseweb="tab-list"] { gap:7px; }
        .stTabs [data-baseweb="tab"] { border-radius:9px;background:#eceef2;padding:8px 15px;height:auto; }
        .stTabs [aria-selected="true"] { background:#f9e7e7;color:#ad3e47; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _clear_scriptlint_data(repo: SQLiteRepository, *, project_id: str) -> None:
    with repo.transaction() as conn:
        conn.execute(
            "DELETE FROM script_tool_events WHERE run_id IN "
            "(SELECT id FROM script_agent_runs WHERE team_id = ? AND project_id = ?)",
            (TEAM_ID, project_id),
        )
        for table in ("script_agent_runs", "script_rules", "script_feedback_events", "script_versions"):
            conn.execute(
                f"DELETE FROM {table} WHERE team_id = ? AND project_id = ?",
                (TEAM_ID, project_id),
            )


def _reset_demo(repo: SQLiteRepository) -> None:
    _clear_scriptlint_data(repo, project_id=_project_id())
    for key in (
        "scriptlint_result",
        "scriptlint_feedback",
        "eval_result",
        "confirm_clear",
    ):
        st.session_state.pop(key, None)
    st.session_state["script_input"] = DEMO_SCRIPT
    st.session_state["episode_input"] = 3
    st.session_state["project_name"] = "我的短剧项目"
    st.session_state["project_code"] = f"project_{uuid.uuid4().hex[:8]}"
    st.session_state["script_title"] = "第3集人物一致性审计"
    st.session_state["version_label"] = "V1"
    st.session_state["demo_stage"] = 1


def _sidebar(repo: SQLiteRepository) -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><div class="brand-mark">S</div><div><div class="brand-title">ScriptLint</div>'
            '<div class="brand-sub">Feedback memory agent</div></div></div>',
            unsafe_allow_html=True,
        )
        st.caption("人物一致性、改稿规则记忆与跨版本审计。")
        st.markdown("<div class='section-label'>当前项目</div>", unsafe_allow_html=True)
        st.markdown(f"**《{html.escape(_project_name())}》**")
        st.caption(f"匿名项目隔离键：{_project_id()}（请勿公开复用）")

        stage = st.session_state.get("demo_stage", 1)
        st.markdown("<div class='section-label'>当前进度</div>", unsafe_allow_html=True)
        labels = ["① 导入并审计", "② 提交改稿规则", "③ 确认后跨版本复用"]
        for index, label in enumerate(labels, start=1):
            color = "#ff8278" if index <= stage else "#676f82"
            st.markdown(f"<div style='color:{color};font-size:12px;line-height:2;'>{label}</div>", unsafe_allow_html=True)

        st.markdown("<div class='section-label'>快捷操作</div>", unsafe_allow_html=True)
        if st.button("载入多维冲突样例", **_stretch(st.button)):
            st.session_state["script_input"] = DEMO_SCRIPT
            st.session_state["episode_input"] = 3
            st.session_state["script_title"] = "第3集多维人物一致性"
        if st.button("载入后续相似任务", **_stretch(st.button)):
            st.session_state["script_input"] = DEMO_FOLLOWUP
            st.session_state["episode_input"] = 4
            st.session_state["script_title"] = "第4集改稿复审"
            st.session_state["version_label"] = "V2"
        if st.button("重置完整演示", **_stretch(st.button)):
            st.session_state["confirm_clear"] = True
        if st.session_state.get("confirm_clear"):
            st.warning("将清空本地 ScriptLint 演示规则与运行记录。")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("确认", key="clear_yes", type="primary"):
                    _reset_demo(repo)
                    st.rerun()
            with c2:
                if st.button("取消", key="clear_no"):
                    st.session_state["confirm_clear"] = False
                    st.rerun()

        st.markdown("<div class='section-label'>运行状态</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:12px;line-height:1.9;color:#bdc3d1;'>"
                    "<span style='color:#60d6b1'>●</span> 本地 SQLite<br>"
                    "<span style='color:#60d6b1'>●</span> 六类文本审计<br>"
                    "<span style='color:#60d6b1'>●</span> 多模态证据契约</div>", unsafe_allow_html=True)
        st.caption("当前只分析剧本文本；视频/音频适配器为后续扩展位。")


def _header() -> None:
    st.markdown(
        '<div class="hero"><div><div class="eyebrow">Character continuity & feedback memory</div>'
        '<h1>审你的剧本，也记住你的改法。</h1>'
        '<p>导入自己的剧本，检查人物动作、外观、知情边界、情绪与道具连续性；'
        '再把你的改稿意见沉淀为项目规则，让后续版本自动复用并保留双向证据。</p></div>'
        '<div class="mode-pill"><span class="mode-dot"></span>文本 Demo · 视频可扩展</div></div>',
        unsafe_allow_html=True,
    )
    stage = st.session_state.get("demo_stage", 1)
    steps = [("01", "导入自有剧本"), ("02", "多维审计"), ("03", "确认改稿规则"), ("04", "后续版本复用")]
    parts = ["<div class='flow'>"]
    active_count = {1: 1, 2: 2, 3: 4}.get(stage, 1)
    for index, (number, label) in enumerate(steps, start=1):
        parts.append(
            f"<div class='flow-item {'active' if index <= active_count else ''}'>"
            f"<span class='flow-n'>{number}</span>{label}</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _new_task() -> ScriptAuditTask:
    return ScriptAuditTask(
        id=f"task_{uuid.uuid4().hex[:8]}",
        team_id=TEAM_ID,
        project_id=_project_id(),
        episode=int(st.session_state.get("episode_input", 3)),
        title=st.session_state.get("script_title", "本集人物一致性审计"),
        script_text=st.session_state.get("script_input", "").strip(),
        version_id=st.session_state.get("current_version_id"),
    )


def _run(agent: ScriptLintAgent, task: ScriptAuditTask) -> ScriptAgentResult:
    return agent.analyze(task=task, run_id=f"run_{uuid.uuid4().hex[:10]}", now=_now())


def _render_input(repo: SQLiteRepository, agent: ScriptLintAgent) -> None:
    st.markdown('<div class="panel"><div class="panel-title">你的剧本项目</div>'
                '<div class="panel-note">支持粘贴或上传 TXT / MD / Fountain 文本。规则按项目隔离，历史版本可再次载入。</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([1.35, 1])
    with c1:
        st.text_input("项目名称", key="project_name", placeholder="例如：雨夜便利店")
    with c2:
        st.text_input("项目代码", key="project_code", help="相同代码的版本会复用同一组已确认规则")

    uploaded = st.file_uploader(
        "上传剧本文件",
        type=["txt", "md", "fountain"],
        help="内容会保存在当前部署实例的 SQLite。公开测试请只上传已脱敏片段。",
    )
    st.caption("隐私提示：内容会保存在当前部署实例；公开测试请只上传已脱敏、已获授权的剧本片段。")
    if uploaded is not None and st.button("读取此文件", key="load_uploaded_script"):
        try:
            st.session_state["script_input"] = _decode_upload(uploaded)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["source_name"] = uploaded.name
            st.success(f"已读取 {uploaded.name}，请检查文本后运行审计。")
            st.rerun()

    versions = repo.list_script_versions(team_id=TEAM_ID, project_id=_project_id())
    if versions:
        labels = {item.id: f"{item.version_label} · 第{item.episode}集 · {item.title}" for item in versions}
        selected = st.selectbox("载入已保存版本", [None] + [item.id for item in versions], format_func=lambda value: "选择历史版本…" if value is None else labels[value])
        if selected and st.button("载入历史版本", key="load_saved_version"):
            item = repo.get_script_version(selected)
            if item:
                st.session_state.update(
                    script_input=item.script_text,
                    episode_input=item.episode,
                    script_title=item.title,
                    version_label=item.version_label,
                    current_version_id=item.id,
                )
                st.rerun()

    with st.form("script_audit_form"):
        m1, m2, m3 = st.columns([1, 1, 2.2])
        with m1:
            st.number_input("集数", min_value=1, max_value=200, key="episode_input")
        with m2:
            st.text_input("版本", key="version_label", placeholder="V1")
        with m3:
            st.text_input("本集标题", key="script_title")
        st.text_area("剧本文本", key="script_input", height=285, placeholder="粘贴场景、动作、人物台词与神态描述…")
        submitted = st.form_submit_button("保存版本并运行多维审计", type="primary", **_stretch(st.form_submit_button))
    st.markdown("</div>", unsafe_allow_html=True)
    if submitted:
        if not st.session_state.get("script_input", "").strip():
            st.warning("请先粘贴或上传剧本文本。")
            return
        source_name = st.session_state.pop("source_name", None)
        version = _save_version(
            repo,
            source_kind=ScriptSourceKind.uploaded if source_name else ScriptSourceKind.pasted,
            source_name=source_name,
        )
        st.session_state["current_version_id"] = version.id
        with st.spinner("正在检索项目记忆、提取六类事实并审计…"):
            result = _run(agent, _new_task())
        st.session_state["scriptlint_result"] = result
        st.session_state["demo_stage"] = 3 if result.metrics.memory_hit_count else 1
        st.rerun()


def _render_result(result: ScriptAgentResult) -> None:
    st.markdown("<div class='section-label'>本轮结果</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("发现问题", len(result.audit.findings))
    c2.metric("提取事实", len(result.task.facts))
    c3.metric("记忆命中 / 应用", f"{result.metrics.memory_hit_count} / {result.metrics.memory_applied_count}")
    c4, c5 = st.columns(2)
    c4.metric("Agent 后端耗时", f"{result.metrics.latency_ms:.1f} ms")
    c5.metric("记忆成本（估算 tokens）", str(result.metrics.estimated_memory_tokens))

    rule_map = {rule.id: rule for rule in result.retrieved_rules}
    fact_by_evidence = {fact.evidence_id: fact for fact in result.task.facts}
    if not result.audit.findings:
        if result.metrics.memory_hit_count == 0:
            message = "未发现可确定的局部矛盾；当前项目也没有已确认的改稿规则。"
        else:
            message = "已检查命中的团队规则，本轮未发现违例。"
        st.markdown(f"<div class='empty'><b>未发现规则问题</b><br>{html.escape(message)}</div>", unsafe_allow_html=True)
    else:
        for finding in result.audit.findings:
            titles = {
                "rule_conflict": "已确认规则互相冲突",
                "fact_inconsistency": "剧本内部连续性矛盾",
                "rule_violation": "剧本违反已确认规则",
                "rule_drift": "规则发生漂移",
            }
            title = titles.get(finding.finding_type.value, "审计发现")
            body = [f"<div class='finding'><div class='finding-title'>{title}</div>",
                    f"<div class='panel-note'>{html.escape(finding.reason)}</div>"]
            for rule_id in finding.rule_ids:
                rule = rule_map.get(rule_id)
                if rule:
                    body.append(
                        f"<div class='source-quote'><b>反馈记忆 · {html.escape(rule.id)}</b><br>"
                        f"“{html.escape(rule.source_excerpt or '无来源摘录')}”</div>"
                    )
            for evidence_id in finding.evidence_ids:
                fact = fact_by_evidence.get(evidence_id)
                if fact:
                    body.append(
                        f"<div class='trace-quote'><b>剧本证据 · 第{fact.line_number or '?'}行</b><br>"
                        f"“{html.escape(fact.evidence_excerpt)}”</div>"
                    )
            if finding.suggestions:
                body.append("<div class='panel-note' style='margin-top:10px'><b>修复建议：</b> " +
                            "　/　".join(html.escape(item) for item in finding.suggestions) + "</div>")
            body.append("</div>")
            st.markdown("".join(body), unsafe_allow_html=True)

    with st.expander(f"查看提取到的 {len(result.task.facts)} 条人物事实"):
        if result.task.facts:
            def dimension(action: str) -> str:
                if action.startswith("appearance_"):
                    return "外观"
                if action.startswith(("use_prop:", "destroy_prop:", "transfer_prop:")):
                    return "道具"
                if action.startswith("use_") or action == "move_with_injured_leg":
                    return "动作"
                if action == "inappropriate_positive_emotion":
                    return "情绪"
                if action in ("identity_reveal", "reveal_secret_location"):
                    return "知情"
                return "其他"
            st.dataframe(
                [
                    {
                        "维度": dimension(fact.action),
                        "角色": fact.subject,
                        "事实": fact.statement,
                        "行号": fact.line_number or "—",
                        "原文": fact.evidence_excerpt,
                    }
                    for fact in result.task.facts
                ],
                hide_index=True,
                **_stretch(st.dataframe),
            )
        else:
            st.caption("没有匹配到当前确定性解析器支持的事实模式；系统不会编造结果。")

    if result.audit.traces:
        st.markdown("<div class='section-label'>记忆使用解释</div>", unsafe_allow_html=True)
        for trace in result.audit.traces:
            rule = rule_map.get(trace.rule_id)
            labels = {
                RuleUseDecision.apply: ("应用", "chip-active"),
                RuleUseDecision.ignore: ("忽略", "chip-ignore"),
                RuleUseDecision.conflict: ("冲突", "chip-conflict"),
            }
            label, css = labels[trace.decision]
            st.markdown(
                f"<div class='rule-card'><span class='status-chip {css}'>{label}</span> "
                f"<span class='mono' style='font-size:11px;color:#8b84a7'>{html.escape(trace.rule_id)}</span>"
                f"<div class='rule-title'>{html.escape(rule.title if rule else trace.rule_id)}</div>"
                f"<div class='rule-meta'>{html.escape(trace.reason)}</div></div>",
                unsafe_allow_html=True,
            )

    with st.expander("查看 Agent 计划与工具调用轨迹"):
        rows = []
        purposes = {step.tool_name: step.purpose for step in result.plan}
        for trace in result.tool_traces:
            rows.append({
                "顺序": trace.sequence,
                "工具": trace.tool_name,
                "目的": purposes.get(trace.tool_name, ""),
                "状态": trace.status.value,
                "输出摘要": trace.output_summary,
                "耗时 ms": round(trace.duration_ms, 3),
            })
        st.dataframe(rows, hide_index=True, **_stretch(st.dataframe))
        st.caption("Token 为字符长度近似值；当前确定性 Demo 的模型调用数为 0。")


def _submit_feedback(agent: ScriptLintAgent, result: ScriptAgentResult, user_text: str) -> None:
    feedback = agent.receive_feedback(
        feedback_id=f"feedback_{uuid.uuid4().hex[:8]}",
        team_id=result.task.team_id,
        project_id=result.task.project_id,
        original_result=("未发现问题" if not result.audit.findings else f"发现 {len(result.audit.findings)} 个问题"),
        user_text=user_text,
        now=_now(),
    )
    st.session_state["scriptlint_feedback"] = feedback
    st.session_state["demo_stage"] = 2


def _render_feedback(
    repo: SQLiteRepository,
    agent: ScriptLintAgent,
    result: ScriptAgentResult,
) -> None:
    st.markdown("<div class='section-label'>纠正并形成记忆</div>", unsafe_allow_html=True)
    with st.form("feedback_form"):
        feedback_text = st.text_area("告诉系统错在哪里", value=DEMO_FEEDBACK, height=105)
        submitted = st.form_submit_button("生成候选规则", type="primary", **_stretch(st.form_submit_button))
    if submitted:
        with st.spinner("正在把纠正形式化为候选规则…"):
            _submit_feedback(agent, result, feedback_text)
        st.rerun()

    feedback: ScriptFeedbackResult | None = st.session_state.get("scriptlint_feedback")
    if not feedback:
        return
    if not feedback.candidates:
        st.warning("这条反馈缺少明确对象、动作或约束词，系统没有编造规则。请补充角色、集数和‘不能/必须’等条件。")
        return
    for candidate in feedback.candidates:
        current = repo.get_script_rule(candidate.id)
        if current is None:
            continue
        css = "chip-candidate" if current.status == ScriptRuleStatus.candidate else "chip-active"
        st.markdown(
            f"<div class='rule-card'><span class='status-chip {css}'>{current.status.value}</span>"
            f"<div class='rule-title'>{html.escape(current.title)}</div>"
            f"<div class='rule-meta'>对象：{html.escape(current.subject)} · 动作：{html.escape(current.action)} · "
            f"范围：第{current.episode_from or 1}—{current.episode_to or '不限'}集 · 置信度 {current.confidence:.0%}</div>"
            f"<div class='source-quote'>来源原话：“{html.escape(current.source_excerpt or '')}”</div></div>",
            unsafe_allow_html=True,
        )
        if current.status == ScriptRuleStatus.candidate:
            c1, c2, c3 = st.columns([1, 1, 4])
            with c1:
                if st.button("确认并复审", key=f"confirm_{current.id}", type="primary"):
                    agent.confirm_rule(current.id)
                    with st.spinner("规则已激活，正在复审同一任务…"):
                        st.session_state["scriptlint_result"] = _run(agent, result.task)
                    st.session_state["demo_stage"] = 3
                    st.rerun()
            with c2:
                if st.button("拒绝", key=f"reject_{current.id}"):
                    agent.reject_rule(current.id)
                    st.rerun()
            with c3:
                st.caption("只有点击确认后，这条规则才会影响后续任务。")


def _workspace(repo: SQLiteRepository, agent: ScriptLintAgent) -> None:
    left, right = st.columns([1.08, .92], gap="large")
    with left:
        _render_input(repo, agent)
    result: ScriptAgentResult | None = st.session_state.get("scriptlint_result")
    if result and result.task.project_id != _project_id():
        result = None
    with right:
        if result:
            _render_result(result)
        else:
            st.markdown("<div class='empty'><b>等待你的剧本</b><br>上传或粘贴一个版本，系统会先检查局部连续性，再应用该项目记忆。</div>", unsafe_allow_html=True)
    if result:
        _render_feedback(repo, agent, result)


def _rule_library(repo: SQLiteRepository, agent: ScriptLintAgent) -> None:
    rules = repo.list_script_rules(team_id=TEAM_ID, project_id=_project_id())
    active = [rule for rule in rules if rule.status == ScriptRuleStatus.active]
    candidates = [rule for rule in rules if rule.status == ScriptRuleStatus.candidate]
    c1, c2, c3 = st.columns(3)
    c1.metric("已确认", len(active))
    c2.metric("待确认", len(candidates))
    c3.metric("规则总数", len(rules))
    if not rules:
        st.markdown("<div class='empty'><b>规则记忆库为空</b><br>回到审计台提交一次纠正，系统会先生成 candidate。</div>", unsafe_allow_html=True)
        return
    for rule in rules:
        css = "chip-active" if rule.status == ScriptRuleStatus.active else "chip-candidate"
        st.markdown(
            f"<div class='rule-card'><span class='status-chip {css}'>{rule.status.value}</span> "
            f"<span class='mono' style='font-size:10px;color:#8d86a9'>{html.escape(rule.id)}</span>"
            f"<div class='rule-title'>{html.escape(rule.title)} · {RULE_TYPE_LABELS.get(rule.rule_type.value, rule.rule_type.value)}</div>"
            f"<div class='rule-meta'>{html.escape(rule.requirement)}<br>"
            f"作用域：{html.escape(rule.project_id)} · 第{rule.episode_from or 1}—{rule.episode_to or '不限'}集 · "
            f"来源：{html.escape(rule.source_feedback_id or '—')}</div>"
            f"<div class='source-quote'>“{html.escape(rule.source_excerpt or '—')}”</div></div>",
            unsafe_allow_html=True,
        )
        if rule.status == ScriptRuleStatus.candidate:
            c1, c2 = st.columns([1, 5])
            with c1:
                if st.button("确认", key=f"library_confirm_{rule.id}", type="primary"):
                    agent.confirm_rule(rule.id)
                    st.rerun()
            with c2:
                if st.button("拒绝并归档", key=f"library_reject_{rule.id}"):
                    agent.reject_rule(rule.id)
                    st.rerun()


def _evaluation() -> None:
    st.markdown('<div class="panel"><div class="panel-title">记忆效果与成本评测</div>'
                '<div class="panel-note">同一批人工构造金标准任务分别运行无记忆和确认记忆两种模式；'
                '覆盖正确应用、超范围忽略、相反规则冲突、候选门禁和跨项目隔离。</div></div>', unsafe_allow_html=True)
    if st.button("运行 11 条双组对照评测", type="primary"):
        with st.spinner("正在运行 22 次独立 Agent 审计…"):
            st.session_state["eval_result"] = run_scriptlint_eval()
    result = st.session_state.get("eval_result")
    if not result:
        st.markdown("<div class='empty'><b>尚未运行评测</b><br>评测完全离线，不消耗 API Token。</div>", unsafe_allow_html=True)
        return
    baseline = next(item for item in result["reports"] if item["mode"] == "no_memory")
    memory = next(item for item in result["reports"] if item["mode"] == "confirmed_memory")
    st.caption(f"数据标签：{result['data_label']} · {result['case_count']} 条任务 × 2 组 · 结果只代表固定人工样例")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("无记忆匹配率", f"{baseline['finding_exact_match_rate']:.1%}")
    c2.metric("确认记忆匹配率", f"{memory['finding_exact_match_rate']:.1%}", delta=f"+{memory['finding_exact_match_rate']-baseline['finding_exact_match_rate']:.1%}")
    c3.metric("同类错误下降", f"{result['same_type_error_reduction']:.0%}")
    c4.metric("跨项目泄漏", result["cross_project_leakage"])
    c5, c6, c7 = st.columns(3)
    c5.metric("记忆决策精确匹配", f"{memory['decision_exact_match_rate']:.0%}")
    c6.metric("P95 后端耗时", f"{memory['p95_latency_ms']:.2f} ms")
    c7.metric("平均记忆成本（估算）", f"{memory['avg_estimated_memory_tokens']:.1f} tokens")
    st.markdown("<div class='section-label'>逐条结果</div>", unsafe_allow_html=True)
    rows = []
    for item in memory["details"]:
        rows.append({
            "案例": item["id"],
            "类别": item["category"],
            "规则决策": "通过" if item["decision_match"] else "失败",
            "问题判断": "通过" if item["finding_match"] else "失败",
            "应用": ", ".join(item["applied"]) or "—",
            "忽略": ", ".join(item["ignored"]) or "—",
            "冲突": ", ".join(item["conflicted"]) or "—",
        })
    st.dataframe(rows, hide_index=True, **_stretch(st.dataframe))
    st.info("这是工程 smoke benchmark，不是行业模型排行榜。下一步会加入少量真实编剧反馈做外部验证。")


def _validation(repo: SQLiteRepository) -> None:
    service = ScriptValidationService(repo)
    summary = service.summarize(team_id=TEAM_ID, project_id=_project_id())
    st.markdown(
        '<div class="panel"><div class="panel-title">少量真实用户验证台</div>'
        '<div class="panel-note">邀请 3–5 位创作者各自导入一段已脱敏剧本，提交自己的改稿规则，再换一个版本复审。'
        '量表只记录匿名编号；不要填写姓名、联系方式或公司信息。</div></div>',
        unsafe_allow_html=True,
    )
    progress = min(summary.participant_count / 3, 1.0)
    st.progress(progress, text=f"方向性验证进度：{summary.participant_count} / 3 位最低样本")
    c1, c2, c3 = st.columns(3)
    c1.metric("匿名参与者", summary.participant_count)
    c2.metric("完成反馈闭环", f"{summary.completion_rate:.0%}")
    c3.metric("规则应用正确", f"{summary.correct_rate:.0%}")
    c4, c5, c6 = st.columns(3)
    c4.metric("解释清晰度", f"{summary.avg_explanation_clarity:.1f} / 5")
    c5.metric("溯源后信任", f"{summary.avg_trace_trust:.1f} / 5")
    c6.metric("愿意继续使用", f"{summary.would_use_rate:.0%}")
    if summary.ready_for_directional_claim:
        st.success("已达到方向性验证最低门槛。路演时必须同时说明样本人数和招募方式。")
    else:
        st.info("尚不足以形成用户结论。未满 3 人时只能说“验证基础设施已完成”，不能说“用户验证通过”。")

    st.markdown("<div class='section-label'>记录一次现场测试</div>", unsafe_allow_html=True)
    role_labels = {
        ValidationRole.screenwriter: "短剧编剧",
        ValidationRole.student_creator: "学生创作者",
        ValidationRole.producer_editor: "制片 / 编辑",
        ValidationRole.other: "其他相关角色",
    }
    judgment_labels = {
        ValidationJudgment.correct: "应用正确",
        ValidationJudgment.partly_correct: "部分正确",
        ValidationJudgment.incorrect: "应用错误",
    }
    with st.form("real_user_validation_form", clear_on_submit=True):
        left, right = st.columns(2)
        with left:
            participant_code = st.text_input("匿名编号", placeholder="例如 P01，不要填写姓名")
            role = st.selectbox("参与者角色", list(ValidationRole), format_func=lambda value: role_labels[value])
            duration_seconds = st.number_input("完成任务耗时（秒）", min_value=1, max_value=1800, value=180)
        with right:
            completed = st.radio("是否独立完成反馈闭环", [True, False], format_func=lambda value: "完成" if value else "未完成", horizontal=True)
            judgment = st.selectbox("确认后的规则应用", list(ValidationJudgment), format_func=lambda value: judgment_labels[value])
            would_use = st.radio("是否愿意在下一次改稿中继续使用", [True, False], format_func=lambda value: "愿意" if value else "不愿意", horizontal=True)
        clarity = st.slider("解释清晰度", min_value=1, max_value=5, value=4, help="1=完全看不懂，5=无需解释即可理解")
        trust = st.slider("看到反馈原话和剧本证据后的信任程度", min_value=1, max_value=5, value=4)
        comment = st.text_area("一句话观察（可选）", max_chars=500, placeholder="只写产品观察，不要写个人信息或真实剧本内容。")
        consent = st.checkbox("参与者同意将以上匿名结果用于本次产品验证")
        submitted = st.form_submit_button("保存匿名验证记录", type="primary", **_stretch(st.form_submit_button))

    if submitted:
        try:
            item = ScriptUserValidation(
                id=f"validation_{uuid.uuid4().hex[:10]}",
                team_id=TEAM_ID,
                project_id=_project_id(),
                participant_code=participant_code,
                role=role,
                scenario_id="own_script_multidimensional_v2",
                completed_feedback_loop=completed,
                rule_judgment=judgment,
                explanation_clarity=clarity,
                trace_trust=trust,
                would_use=would_use,
                duration_seconds=int(duration_seconds),
                comment=comment.strip() or None,
                consent=consent,
                created_at=_now(),
            )
            service.record(item)
        except sqlite3.IntegrityError:
            st.error("该匿名编号已经记录过当前场景，请换一个编号或检查是否重复提交。")
        except Exception as exc:
            st.error(f"未保存：{exc}")
        else:
            st.success("匿名验证结果已保存到本地 SQLite。")
            st.rerun()

    rows = service.list(team_id=TEAM_ID, project_id=_project_id())
    if rows:
        st.markdown("<div class='section-label'>已记录结果</div>", unsafe_allow_html=True)
        role_labels_by_value = {key.value: value for key, value in role_labels.items()}
        judgment_labels_by_value = {key.value: value for key, value in judgment_labels.items()}
        st.dataframe(
            [
                {
                    "编号": row.participant_code,
                    "角色": role_labels_by_value[row.role.value],
                    "完成闭环": "是" if row.completed_feedback_loop else "否",
                    "应用判断": judgment_labels_by_value[row.rule_judgment.value],
                    "清晰度": row.explanation_clarity,
                    "信任": row.trace_trust,
                    "愿意使用": "是" if row.would_use else "否",
                    "耗时": f"{row.duration_seconds or '—'} 秒",
                }
                for row in rows
            ],
            hide_index=True,
            **_stretch(st.dataframe),
        )
        st.download_button(
            "导出匿名 CSV",
            data=service.export_csv(team_id=TEAM_ID, project_id=_project_id()).encode("utf-8-sig"),
            file_name="scriptlint_user_validation.csv",
            mime="text/csv",
        )


def _about() -> None:
    st.markdown('<div class="panel"><div class="panel-title">现在能做什么，未来怎样进入视频审片？</div>'
                '<div class="panel-note" style="font-size:14px;max-width:850px;margin-top:12px">'
                '现在：导入自有剧本 → 提取人物事实 → 检查局部连续性 → 接收用户改稿意见 → '
                '逐条确认规则 → 在后续版本自动复用。每个问题都能回到改稿原话和剧本行号。</div><hr>'
                '<div class="section-label">产品边界</div>'
                '<div class="panel-note" style="font-size:13px">当前 Demo 是透明的确定性文本解析器，覆盖身份/知情、动作能力、'
                '外观、情绪情境和道具连续性等明确模式，不声称理解任意表达。后续 ASR、字幕、音频和视频帧提取器会输出同一种证据对象，'
                '因此可以沿用项目规则、版本和审计报告；当前页面不宣称已经完成视频理解。</div></div>',
                unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="ScriptLint · 短剧反馈记忆 Agent", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
    _inject_css()
    st.session_state.setdefault("script_input", DEMO_SCRIPT)
    st.session_state.setdefault("episode_input", 3)
    st.session_state.setdefault("project_name", "我的短剧项目")
    st.session_state.setdefault("project_code", f"project_{uuid.uuid4().hex[:8]}")
    st.session_state.setdefault("script_title", "第3集人物一致性审计")
    st.session_state.setdefault("version_label", "V1")
    st.session_state.setdefault("demo_stage", 1)
    db_path = os.getenv("DP_DB_PATH", str(Path(PROJECT_ROOT) / "scriptlint_demo.db"))
    repo, agent = _runtime(db_path)
    _sidebar(repo)
    _header()
    nav = st.radio("导航", ["剧本审计", "项目规则", "固定评测", "用户验证", "演进路线"], horizontal=True, label_visibility="collapsed")
    if nav == "剧本审计":
        _workspace(repo, agent)
    elif nav == "项目规则":
        _rule_library(repo, agent)
    elif nav == "固定评测":
        _evaluation()
    elif nav == "用户验证":
        _validation(repo)
    else:
        _about()


if __name__ == "__main__":
    main()
