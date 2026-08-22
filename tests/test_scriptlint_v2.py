from __future__ import annotations

from datetime import datetime, timezone

from repositories import SQLiteRepository
from schemas import (
    FindingType,
    ScriptAuditTask,
    ScriptFeedbackEvent,
    ScriptSourceKind,
    ScriptVersion,
)
from services.scriptlint_agent import ScriptLintAgent
from services.scriptlint_audit_service import ScriptLintAuditService
from services.review_pipeline import script_facts_to_observations
from schemas import ReviewAsset, ReviewModality
from scriptlint_app import _clear_scriptlint_data
from tools.scriptlint_tools import extract_script_facts, propose_script_rules


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
SCRIPT = """第3集 内景 灵堂 日
女主左手缠着厚厚的绷带，却用左手提起沉重的箱子。
男主左脸有一道新伤。
女主：账本就在城南仓库。
女主开心地大笑：太好了！
反派把戒指扔进火里烧毁。
男主从口袋拿出戒指。
男主右脸的伤口渗出血迹。"""


def _task() -> ScriptAuditTask:
    return ScriptAuditTask(
        id="task_v2",
        team_id="team_v2",
        project_id="project_v2",
        episode=3,
        title="用户剧本 V2",
        script_text=SCRIPT,
    )


def test_multidimensional_extractor_preserves_lines_and_evidence():
    facts = extract_script_facts(_task())
    actions = {fact.action for fact in facts}
    assert "use_左手" in actions
    assert "appearance_左脸_wound" in actions
    assert "appearance_右脸_wound" in actions
    assert "reveal_secret_location" in actions
    assert "inappropriate_positive_emotion" in actions
    assert "destroy_prop:戒指" in actions
    assert "use_prop:戒指" in actions
    assert next(fact for fact in facts if fact.action == "inappropriate_positive_emotion").subject == "女主"
    assert all(fact.line_number and fact.evidence_excerpt for fact in facts)


def test_multiple_feedback_lines_become_separate_candidates():
    feedback = ScriptFeedbackEvent(
        id="feedback_v2",
        team_id="team_v2",
        project_id="project_v2",
        original_result="待审计",
        user_text=(
            "女主左手受伤，第1到3集不能用左手提重物；"
            "女主不知道账本位置，不能说出账本在哪；"
            "男主伤口在左脸，不能写成右脸；"
            "葬礼场景女主不能开心大笑；"
            "戒指已经销毁，男主不能再拿出戒指"
        ),
        created_at=NOW,
    )
    rules = propose_script_rules(feedback)
    assert len(rules) == 5
    assert len({rule.rule_type for rule in rules}) == 5
    assert all(rule.source_excerpt for rule in rules)


def test_fact_consistency_catches_face_and_destroyed_prop_without_memory():
    task = _task().model_copy(update={"facts": extract_script_facts(_task())})
    result = ScriptLintAuditService().audit(task=task, rules=[])
    assert [item.finding_type for item in result.findings].count(FindingType.fact_inconsistency) == 2
    assert all(not item.rule_ids for item in result.findings)


def test_confirmed_user_rules_are_reused_on_later_version():
    repo = SQLiteRepository(":memory:")
    repo.init()
    agent = ScriptLintAgent(repo)
    learned = agent.receive_feedback(
        feedback_id="feedback_rules",
        team_id="team_v2",
        project_id="project_v2",
        original_result="初稿审计",
        user_text="女主左手受伤，第1到3集不能用左手提重物；女主不知道账本位置，不能说出账本在哪",
        now=NOW,
    )
    for candidate in learned.candidates:
        agent.confirm_rule(candidate.id)

    result = agent.analyze(task=_task(), run_id="run_later_version", now=NOW)
    assert result.metrics.memory_applied_count == 2
    assert len([item for item in result.audit.findings if item.rule_ids]) == 2
    repo.close()


def test_user_script_version_round_trip():
    repo = SQLiteRepository(":memory:")
    repo.init()
    version = ScriptVersion(
        id="version_001",
        team_id="team_v2",
        project_id="project_v2",
        project_name="我的短剧",
        version_label="V1",
        episode=3,
        title="第3集",
        script_text=SCRIPT,
        source_kind=ScriptSourceKind.uploaded,
        source_name="episode03.txt",
        content_hash="hash",
        created_at=NOW,
    )
    repo.insert_script_version(version)
    assert repo.get_script_version(version.id) == version
    assert repo.list_script_versions(team_id="team_v2", project_id="project_v2") == [version]
    repo.close()


def test_text_evidence_can_enter_future_multimodal_pipeline():
    facts = extract_script_facts(_task())
    asset = ReviewAsset(
        id="asset_script_v1",
        project_id="project_v2",
        version_id="version_001",
        modality=ReviewModality.script_text,
        display_name="第3集剧本",
        content_hash="hash",
    )
    observations = script_facts_to_observations(facts, asset=asset)
    assert observations[0].evidence.modality == ReviewModality.script_text
    assert observations[0].evidence.locator.line_number == facts[0].line_number
    assert observations[0].action == facts[0].action


def test_specific_dialogue_can_be_bound_to_the_correct_speaker():
    feedback = ScriptFeedbackEvent(
        id="feedback_dialogue",
        team_id="team_v2",
        project_id="project_v2",
        original_result="待审计",
        user_text="“账本就在城南仓库”这句台词不能让男主说",
        created_at=NOW,
    )
    rule = propose_script_rules(feedback)[0].model_copy(update={"status": "active"})
    task = ScriptAuditTask(
        id="task_dialogue",
        team_id="team_v2",
        project_id="project_v2",
        episode=3,
        title="台词归属",
        script_text="男主：账本就在城南仓库。",
    )
    task = task.model_copy(update={"facts": extract_script_facts(task)})
    result = ScriptLintAuditService().audit(task=task, rules=[rule])
    assert len(result.findings) == 1
    assert result.findings[0].finding_type == FindingType.rule_violation


def test_real_character_names_are_discovered_from_dialogue_headers():
    task = ScriptAuditTask(
        id="task_named_cast",
        team_id="team_v2",
        project_id="project_v2",
        episode=2,
        title="真实角色名",
        script_text="林夏左手缠着绷带，却用左手提起箱子。\n林夏：我没事。",
    )
    facts = extract_script_facts(task)
    assert any(fact.subject == "林夏" and fact.action == "use_左手" for fact in facts)
    assert any(fact.subject == "林夏" and fact.action == "speak_dialogue" for fact in facts)


def test_reset_only_clears_the_current_public_test_project():
    repo = SQLiteRepository(":memory:")
    repo.init()
    agent = ScriptLintAgent(repo)
    for project_id in ("project_a", "project_b"):
        learned = agent.receive_feedback(
            feedback_id=f"feedback_{project_id}",
            team_id="team_scriptlint_demo",
            project_id=project_id,
            original_result="待审计",
            user_text="女主不知道账本位置，不能说出账本在哪",
            now=NOW,
        )
        agent.confirm_rule(learned.candidates[0].id)

    _clear_scriptlint_data(repo, project_id="project_a")
    assert repo.list_script_rules(team_id="team_scriptlint_demo", project_id="project_a") == []
    assert len(repo.list_script_rules(team_id="team_scriptlint_demo", project_id="project_b")) == 1
    repo.close()
