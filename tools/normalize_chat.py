"""normalize_chat 工具（规格 7.2）。

确定性，不调用模型。把原始群聊文本规范化为 Message 列表，
对无法解析的行给出 ParseWarning（规格 4.1）。

支持两种格式（规格 3.2）：
  - "姓名：消息"
  - 带时间戳 "18:02 A：要不 PPT 做成蓝色？"
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta

from schemas import ChatLog, DataSourceLabel, Message, ParseWarning

_CST = timezone(timedelta(hours=8))
# 固定演示日期，避免依赖系统时钟，保证测试可重复
_DEMO_DATE = datetime(2026, 8, 20, tzinfo=_CST)

# 时间戳前缀：HH:MM 或 H:MM（规格 12.1 演示数据形如 "18:02"）
_TS_PATTERN = re.compile(r"^(\d{1,2}:\d{2})\s+(.+)$")
# 说话人：内容（兼容中文：与英文:）
_SPEAKER_PATTERN = re.compile(r"^(.+?)\s*[:：]\s*(.+)$")


def normalize_chat(
    raw_text: str,
    *,
    project_id: str,
    source_label: DataSourceLabel | None = None,
) -> ChatLog:
    """原始文本 -> ChatLog（规格 4.1）。

    逐行解析：先尝试剥离时间戳前缀，再匹配「说话人：内容」。
    无法识别说话人的行进入 warnings，不丢弃以便用户查看。
    """
    messages: list[Message] = []
    warnings: list[ParseWarning] = []

    for idx, raw_line in enumerate(raw_text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue

        sent_at: datetime | None = None
        body = line

        # 1. 尝试剥离时间戳前缀
        ts_match = _TS_PATTERN.match(line)
        if ts_match:
            sent_at = _parse_time(ts_match.group(1))
            body = ts_match.group(2).strip()

        # 2. 匹配「说话人：内容」
        sp_match = _SPEAKER_PATTERN.match(body)
        if not sp_match:
            warnings.append(ParseWarning(line=line, reason="无法识别说话人"))
            continue

        sender = sp_match.group(1).strip()
        content = sp_match.group(2).strip()
        if not sender or not content:
            warnings.append(ParseWarning(line=line, reason="说话人或内容为空"))
            continue

        msg_id = f"msg_{idx:03d}"
        source_hash = hashlib.sha1(raw_line.encode("utf-8")).hexdigest()[:12]

        messages.append(
            Message(
                id=msg_id,
                project_id=project_id,
                sender=sender,
                sent_at=sent_at,
                content=content,
                source_hash=source_hash,
            )
        )

    return ChatLog(
        project_id=project_id,
        messages=messages,
        warnings=warnings,
        source_label=source_label,
    )


def _parse_time(hhmm: str) -> datetime | None:
    """把 'HH:MM' 解析为带时区的 datetime（固定演示日期 2026-08-20）。"""
    try:
        h, m = hhmm.split(":")
        return datetime(2026, 8, 20, int(h), int(m), tzinfo=_CST)
    except (ValueError, KeyError):
        return None
