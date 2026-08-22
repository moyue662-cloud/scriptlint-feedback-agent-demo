"""DecisionPatch 持久层。

对应规格 7.4 的 repositories/ 目录与第 5.3 节的 8 张表。
通过 Repository 接口保留替换能力（规格 8 / 图 4）。
"""
from __future__ import annotations

from .sqlite import SQLiteRepository

__all__ = ["SQLiteRepository"]
