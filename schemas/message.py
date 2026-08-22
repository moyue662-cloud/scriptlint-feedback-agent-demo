"""消息与聊天记录模型。

对应规格 5.3 的 messages 表，以及 4.1 节"系统规范化消息，提示无法解析的行"。
支持两种输入格式（规格 3.2）：
  - "姓名：消息"
  - 带时间戳 "18:02 A：要不 PPT 做成蓝色？"
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DataSourceLabel(str, Enum):
    """数据来源标签（规格 8.3）。演示数据必须标明来源，不得伪装成真实数据。"""

    real_anonymized = "real_anonymized"  # 真实脱敏
    synthetic = "synthetic"  # 人工构造
    eval_sample = "eval_sample"  # 评测样例


class Message(BaseModel):
    """一条规范化后的群聊消息。"""

    id: str = Field(description="消息唯一 ID，如 msg_018")
    project_id: str = Field(description="所属项目")
    sender: str = Field(description="说话人（脱敏后姓名或 A/B/C 代称）")
    sent_at: datetime | None = Field(
        default=None,
        description="消息时间；无时间戳的行可为空",
    )
    content: str = Field(description="消息正文")
    source_hash: str | None = Field(
        default=None,
        description="原始输入行的哈希，用于去重与证据溯源",
    )


class ParseWarning(BaseModel):
    """规范化阶段对无法解析的行给出的提示（规格 4.1）。"""

    line: str = Field(description="原始无法解析的行")
    reason: str = Field(description="无法解析的原因，如缺少说话人")


class ChatLog(BaseModel):
    """一段群聊的规范化结果。"""

    project_id: str = Field(description="所属项目")
    messages: list[Message] = Field(default_factory=list, description="规范化后的消息列表")
    warnings: list[ParseWarning] = Field(
        default_factory=list,
        description="无法解析的行及其原因",
    )
    source_label: DataSourceLabel | None = Field(
        default=None,
        description="数据来源标签；演示数据必须标注",
    )
