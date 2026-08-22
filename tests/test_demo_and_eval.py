"""完整 demo 的离线 Provider 与固定评测烟测。"""
from __future__ import annotations

from providers.demo_provider import build_demo_provider
from tools.extract_decisions import ExtractDecisionsOutput
from tools.propose_memory import ProposeMemoryOutput
from eval.run_eval import load_fixtures, run_offline_eval


def test_demo_provider_has_evidence_and_changes_after_memory():
    provider = build_demo_provider()
    first = provider.generate_structured(
        system_prompt="",
        user_prompt="[msg_000] A: 要不 PPT 做成蓝色？",
        response_model=ExtractDecisionsOutput,
    )
    second = provider.generate_structured(
        system_prompt="",
        user_prompt="适用记忆：\n记忆 cand_000 (apply): 命中\n[msg_000] A: 要不 PPT 做成蓝色？",
        response_model=ExtractDecisionsOutput,
    )
    assert first.decisions[0].type.value == "confirmed"
    assert second.decisions[0].type.value == "proposal"
    assert second.decisions[0].evidence_message_ids == ["msg_000"]


def test_demo_provider_proposes_structured_memory():
    provider = build_demo_provider()
    result = provider.generate_structured(
        system_prompt="",
        user_prompt="用户纠正：这只是建议，还没定",
        response_model=ProposeMemoryOutput,
    )
    assert result.candidates
    assert result.candidates[0].rule_type.value == "speech_act"


def test_fixed_eval_has_spec_buckets_and_three_reports():
    rows = load_fixtures()
    result = run_offline_eval()
    assert len(rows) == 30
    assert [report["mode"] for report in result["reports"]] == [
        "no_memory",
        "full_history",
        "decisionpatch",
    ]
    decisionpatch = result["reports"][-1]
    assert decisionpatch["classification"]["accuracy"] == 1.0
    assert decisionpatch["memory"]["cross_team_leakage"] == 0
