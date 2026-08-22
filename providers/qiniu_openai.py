"""七牛云 OpenAI 兼容接口 Provider。

对应规格 §0.2 "七牛云兼容 OpenAI 格式的推理接口作为默认模型通道"。
使用 openai SDK，通过 base_url 指向七牛云端点。
openai 包延迟导入：Mock 模式或测试无需安装 openai。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from .llm_base import LLMProvider, ProviderError, schema_instruction


class QiniuOpenAIProvider:
    """七牛云 OpenAI 兼容 Provider（规格 §0.2 / §8.2）。

    构造时仅校验配置；openai 客户端在首次调用时延迟创建，
    使 Mock 模式或单元测试无需安装 openai 包。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        max_retries: int = 1,
    ) -> None:
        if not (base_url and api_key and model):
            raise ProviderError(
                "QiniuOpenAIProvider 需要 base_url、api_key、model 三者齐全"
            )
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._default_temperature = temperature
        self._max_retries = max_retries
        self._client: Any = None  # 延迟初始化

    # -- 内部 ------------------------------------------------------------- #

    def _get_client(self) -> Any:
        """延迟创建 OpenAI 客户端。"""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ProviderError(
                    "未安装 openai 包；请 pip install openai 或使用 mock provider"
                ) from e
            self._client = OpenAI(
                base_url=self._base_url, api_key=self._api_key
            )
        return self._client

    def _call_llm(
        self, system_prompt: str, user_prompt: str, temperature: float
    ) -> str:
        """调用模型，返回原始文本内容。"""
        client = self._get_client()
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise ProviderError(f"模型调用失败: {e}") from e

        content = resp.choices[0].message.content
        if not content:
            raise ProviderError("模型返回空内容")
        return content

    # -- 公开接口（规格 §8.2）--------------------------------------------- #

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> BaseModel:
        """调用模型并返回经 response_model 校验的结构化结果。

        失败时重试 max_retries 次（规格 §0.2），仍失败则抛出 ProviderError，
        由上层进入可解释降级。
        """
        full_system = system_prompt + schema_instruction(response_model)
        last_error: Exception | None = None
        attempts = self._max_retries + 1

        for _ in range(attempts):
            try:
                raw = self._call_llm(full_system, user_prompt, temperature)
                return response_model.model_validate_json(raw)
            except (ValidationError, json.JSONDecodeError, ProviderError) as e:
                last_error = e
                continue

        raise ProviderError(
            f"结构化输出校验失败（重试 {self._max_retries} 次后仍失败）: {last_error}"
        )
