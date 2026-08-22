"""离线 Mock Provider。

对应规格 §0.2 "保留 Provider Adapter 和离线 Mock"、§3.2 "预缓存演示与
离线 Mock，保证网络异常时能完成核心演示"。

三种响应模式（按优先级）：
1. builder：register_builder(cls, fn) —— 调用 fn(user_prompt) 动态生成，
   可基于 prompt 内容返回不同结果（演示场景用）。
2. 固定注册：register(cls, instance) —— 始终返回 instance 的深拷贝。
3. 自动构造：对未注册的模型，用类型自省构造最小合法实例。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, get_args, get_origin

from pydantic import BaseModel

from .llm_base import LLMProvider, ProviderError

_CST = timezone(timedelta(hours=8))
_DEFAULT_DT = datetime(2026, 8, 20, 12, 0, tzinfo=_CST)


class MockProvider:
    """离线 Mock Provider。

    - register(cls, instance)：对该类始终返回 instance 的深拷贝。
    - register_builder(cls, fn)：对该类调用 fn(user_prompt) 动态生成。
    - 未注册的类：自动构造最小合法实例。
    - call_log：记录每次调用，便于测试断言。
    """

    def __init__(self) -> None:
        self._responses: dict[type[BaseModel], BaseModel] = {}
        self._builders: dict[type[BaseModel], Callable[[str], BaseModel]] = {}
        self.call_log: list[dict[str, Any]] = []

    def register(self, model_cls: type[BaseModel], response: BaseModel) -> None:
        """注册固定响应。"""
        self._responses[model_cls] = response

    def register_builder(
        self,
        model_cls: type[BaseModel],
        builder: Callable[[str], BaseModel],
    ) -> None:
        """注册动态构建器（可基于 user_prompt 内容生成响应）。"""
        self._builders[model_cls] = builder

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> BaseModel:
        self.call_log.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model.__name__,
                "temperature": temperature,
            }
        )

        # 1. builder 优先（可基于 prompt 内容动态生成）
        builder = self._builders.get(response_model)
        if builder is not None:
            return builder(user_prompt)

        # 2. 固定注册响应（返回深拷贝，避免调用方修改污染缓存）
        cached = self._responses.get(response_model)
        if cached is not None:
            return cached.model_copy(deep=True)

        # 3. 自动构造最小合法实例
        try:
            return _construct_minimal(response_model)
        except Exception as e:
            raise ProviderError(
                f"MockProvider 无法为 {response_model.__name__} "
                f"构造默认响应: {e}"
            ) from e


# --------------------------------------------------------------------------- #
# 类型自省：构造最小合法实例
# --------------------------------------------------------------------------- #


def _construct_minimal(model_cls: type[BaseModel]) -> BaseModel:
    """用类型自省构造一个最小合法的 BaseModel 实例。"""
    data: dict[str, Any] = {}
    for name, field in model_cls.model_fields.items():
        if field.is_required():
            data[name] = _default_for(field.annotation)
        elif field.default_factory is not None:
            # 显式提供 default_factory 的值，避免 model_construct 遗漏
            data[name] = field.default_factory()
    try:
        return model_cls.model_validate(data)
    except Exception:
        # 校验失败（如 model_validator 约束）时退回到无校验构造
        return model_cls.model_construct(**data)


def _default_for(annotation: Any) -> Any:
    """为给定类型注解返回一个合理的默认值。"""
    origin = get_origin(annotation)
    args = get_args(annotation)

    # None 类型
    if annotation is type(None):
        return None

    # list[X] 或 bare list -> []
    if origin is list or annotation is list:
        return []

    # dict[K, V] 或 bare dict -> {}
    if origin is dict or annotation is dict:
        return {}

    # Union / Optional（含 X | None 与 Optional[X]）
    if origin is not None:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _default_for(non_none[0])
        return None

    # 基本类型
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if annotation is datetime:
        return _DEFAULT_DT

    # Enum -> 第一个值
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return list(annotation)[0]

    # 嵌套 BaseModel -> 递归构造
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _construct_minimal(annotation)

    # 兜底：返回 None（字段若不允许 None 会在 model_validate 阶段报错）
    return None
