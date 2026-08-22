"""Provider 工厂与导出。

对应规格 §0.2 "七牛云兼容 OpenAI 格式的推理接口作为默认模型通道；
保留 Provider Adapter 和离线 Mock"。
"""
from __future__ import annotations

from config import CONFIG, AppConfig

from .llm_base import LLMProvider, ProviderError, schema_instruction
from .mock_provider import MockProvider
from .qiniu_openai import QiniuOpenAIProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "MockProvider",
    "QiniuOpenAIProvider",
    "schema_instruction",
    "get_provider",
]


def get_provider(config: AppConfig | None = None) -> LLMProvider:
    """根据配置返回 Provider 实例（规格 §0.2）。

    - effective_provider == "mock"  -> MockProvider
    - effective_provider == "qiniu" -> QiniuOpenAIProvider
    - qiniu 未配置时自动降级为 mock（规格 §0.2 可解释降级）
    """
    cfg = config or CONFIG
    name = cfg.effective_provider

    if name == "mock":
        return MockProvider()
    if name == "qiniu":
        return QiniuOpenAIProvider(
            base_url=cfg.qiniu.base_url,
            api_key=cfg.qiniu.api_key,
            model=cfg.qiniu.model,
            temperature=cfg.qiniu.temperature,
            max_retries=cfg.llm_max_retries,
        )
    raise ProviderError(f"未知 provider: {name}")
