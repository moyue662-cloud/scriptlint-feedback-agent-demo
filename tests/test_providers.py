"""Provider 层测试（Part 4 退出条件）。

验证：
- Mock 可返回注册响应、自动构造、builder 动态生成
- Mock 返回的结果通过 Pydantic 校验（规格 §0.2）
- Qiniu 未配置时抛出 ProviderError
- 工厂函数按配置返回正确类型，qiniu 未配置时降级 mock
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from pydantic import BaseModel

from config import AppConfig, QiniuConfig
from providers import (
    LLMProvider,
    MockProvider,
    ProviderError,
    QiniuOpenAIProvider,
    get_provider,
)
from schemas import DecisionRecord, DecisionType, MemoryRule, RuleType

_CST = timezone(timedelta(hours=8))


# ---------- 测试用模型 ---------- #


class _SimpleResult(BaseModel):
    """用于测试自动构造的简单模型。"""

    name: str
    count: int
    score: float
    flag: bool
    items: list[str] = []
    note: str | None = None


class _NestedResult(BaseModel):
    """含嵌套 BaseModel 与 Enum 的模型。"""

    title: str
    decision: DecisionRecord
    rule_type: RuleType


# ---------- MockProvider：注册响应 ---------- #


def test_mock_registered_response_returned():
    mock = MockProvider()
    d = DecisionRecord(
        id="dec_1",
        team_id="t",
        project_id="p",
        type=DecisionType.confirmed,
        summary="测试",
        evidence_message_ids=["m1"],
    )
    mock.register(DecisionRecord, d)

    result = mock.generate_structured(
        system_prompt="sys", user_prompt="usr", response_model=DecisionRecord
    )
    assert result.id == "dec_1"
    assert result.type == DecisionType.confirmed


def test_mock_returns_copy_not_same_instance():
    """注册响应应返回深拷贝，避免调用方修改污染缓存。"""
    mock = MockProvider()
    d = DecisionRecord(
        id="dec_1",
        team_id="t",
        project_id="p",
        type=DecisionType.proposal,
        summary="x",
        evidence_message_ids=["m1"],
    )
    mock.register(DecisionRecord, d)

    r1 = mock.generate_structured(
        system_prompt="", user_prompt="", response_model=DecisionRecord
    )
    r2 = mock.generate_structured(
        system_prompt="", user_prompt="", response_model=DecisionRecord
    )
    assert r1 is not r2
    assert r1 is not d


# ---------- MockProvider：自动构造 ---------- #


def test_mock_auto_construct_simple():
    mock = MockProvider()
    result = mock.generate_structured(
        system_prompt="", user_prompt="", response_model=_SimpleResult
    )
    assert isinstance(result, _SimpleResult)
    assert result.name == ""
    assert result.count == 0
    assert result.score == 0.0
    assert result.flag is False
    assert result.items == []
    assert result.note is None


def test_mock_auto_construct_nested():
    mock = MockProvider()
    result = mock.generate_structured(
        system_prompt="", user_prompt="", response_model=_NestedResult
    )
    assert isinstance(result, _NestedResult)
    assert result.title == ""
    assert isinstance(result.decision, DecisionRecord)
    assert isinstance(result.rule_type, RuleType)


# ---------- MockProvider：builder ---------- #


def test_mock_builder_dynamic():
    mock = MockProvider()

    def build_decision(prompt: str) -> DecisionRecord:
        if "蓝色" in prompt:
            return DecisionRecord(
                id="dec_blue",
                team_id="t",
                project_id="p",
                type=DecisionType.proposal,
                summary="蓝色主题",
                evidence_message_ids=["m1"],
            )
        return DecisionRecord(
            id="dec_other",
            team_id="t",
            project_id="p",
            type=DecisionType.conflict,
            summary="其他",
        )

    mock.register_builder(DecisionRecord, build_decision)

    r1 = mock.generate_structured(
        system_prompt="",
        user_prompt="要不 PPT 做成蓝色？",
        response_model=DecisionRecord,
    )
    assert r1.id == "dec_blue"
    assert r1.type == DecisionType.proposal

    r2 = mock.generate_structured(
        system_prompt="",
        user_prompt="随便说点",
        response_model=DecisionRecord,
    )
    assert r2.id == "dec_other"


# ---------- MockProvider：call_log ---------- #


def test_mock_call_log():
    mock = MockProvider()
    mock.generate_structured(
        system_prompt="S",
        user_prompt="U",
        response_model=_SimpleResult,
        temperature=0.3,
    )
    assert len(mock.call_log) == 1
    entry = mock.call_log[0]
    assert entry["system_prompt"] == "S"
    assert entry["user_prompt"] == "U"
    assert entry["response_model"] == "_SimpleResult"
    assert entry["temperature"] == 0.3


# ---------- QiniuOpenAIProvider：未配置 ---------- #


def test_qiniu_requires_config():
    with pytest.raises(ProviderError):
        QiniuOpenAIProvider(base_url="", api_key="k", model="m")
    with pytest.raises(ProviderError):
        QiniuOpenAIProvider(base_url="u", api_key="", model="m")
    with pytest.raises(ProviderError):
        QiniuOpenAIProvider(base_url="u", api_key="k", model="")


# ---------- 工厂函数 ---------- #


def test_factory_returns_mock_by_default():
    cfg = AppConfig()  # 默认 provider=mock
    provider = get_provider(cfg)
    assert isinstance(provider, MockProvider)


def test_factory_falls_back_to_mock_when_qiniu_unconfigured():
    cfg = AppConfig(provider="qiniu")  # qiniu 未配置 -> 降级 mock
    provider = get_provider(cfg)
    assert isinstance(provider, MockProvider)


def test_factory_returns_qiniu_when_configured():
    cfg = AppConfig(
        provider="qiniu",
        qiniu=QiniuConfig(
            base_url="https://example.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        ),
    )
    provider = get_provider(cfg)
    assert isinstance(provider, QiniuOpenAIProvider)


# ---------- Protocol 兼容性 ---------- #


def test_mock_is_llm_provider():
    mock = MockProvider()
    assert isinstance(mock, LLMProvider)


# ---------- 结构化输出通过校验（规格 §0.2）---------- #


def test_mock_output_passes_validation():
    mock = MockProvider()
    mock.register(
        MemoryRule,
        MemoryRule(
            id="mem_1",
            team_id="t",
            rule_type=RuleType.speech_act,
            trigger="包含'要不'",
            instruction="标记为 proposal",
            created_at=datetime(2026, 8, 20, tzinfo=_CST),
        ),
    )
    result = mock.generate_structured(
        system_prompt="", user_prompt="", response_model=MemoryRule
    )
    assert isinstance(result, MemoryRule)
    assert result.id == "mem_1"
    assert result.rule_type == RuleType.speech_act
