"""LLM Provider 抽象层。

对应规格 §8.2 的 LLMProvider Protocol 与 §0.2 的"所有模型输出都要经过
schema 校验；失败时重试一次，再进入可解释降级"。
"""
from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ProviderError(RuntimeError):
    """Provider 调用或结构化校验失败，由上层进入可解释降级。"""


@runtime_checkable
class LLMProvider(Protocol):
    """模型 Provider 协议（规格 §8.2）。

    所有决策识别必须符合 JSON Schema（规格 §7.3）；本接口强制返回
    经过 Pydantic 校验的 BaseModel 实例，杜绝自由文本作为系统事实。
    """

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> BaseModel:
        """调用模型并返回经 response_model 校验的结构化结果。

        失败时重试一次（规格 §0.2），仍失败则抛出 ProviderError。
        """
        ...


def schema_instruction(response_model: type[BaseModel]) -> str:
    """生成 JSON Schema 指令文本，拼入 system prompt。

    让模型知道期望的输出结构，减少格式错误（规格 §9.1 "返回严格 JSON"）。
    """
    schema = response_model.model_json_schema()
    return (
        "\n\n--- 输出格式 ---\n"
        "你必须返回严格的 JSON，不输出 Markdown 代码块或任何额外文字。\n"
        "JSON 必须符合以下 JSON Schema：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    )
