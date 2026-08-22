"""SQLite 持久层。

对应规格 5.3 的 8 张表，以及第 6 节记忆系统的检索需求。
设计要点：
- 单体优先（规格图 4），用标准库 sqlite3，不引入 ORM。
- 通过 Repository 接口保留替换能力（规格 8 / 图 4）。
- 所有查询参数化，杜绝 SQL 注入。
- 复杂字段（evidence_message_ids）以 JSON 文本落库，读出时还原。
- 日期时间统一以 ISO 8601 字符串存储。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from schemas import (
    AgentRun,
    DecisionRecord,
    FeedbackEvent,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    Message,
    RuleType,
    ScriptAgentResult,
    ScriptFeedbackEvent,
    ScriptRule,
    ScriptRuleEffect,
    ScriptRuleSeverity,
    ScriptRuleStatus,
    ScriptRuleType,
    ScriptSourceKind,
    ScriptToolStatus,
    ScriptToolTrace,
    ScriptUserValidation,
    ScriptVersion,
    ValidationJudgment,
    ValidationRole,
)

# --------------------------------------------------------------------------- #
# DDL：8 张表（规格 5.3）
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,
    team_id    TEXT NOT NULL,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    FOREIGN KEY (team_id) REFERENCES teams(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    sender      TEXT NOT NULL,
    sent_at     TEXT,
    content     TEXT NOT NULL,
    source_hash TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id             TEXT PRIMARY KEY,
    team_id        TEXT NOT NULL,
    project_id     TEXT NOT NULL,
    type           TEXT NOT NULL,
    summary        TEXT NOT NULL,
    owner          TEXT,
    deadline       TEXT,
    status         TEXT NOT NULL DEFAULT 'open',
    confidence     REAL NOT NULL DEFAULT 0.5,
    created_by     TEXT NOT NULL DEFAULT 'agent',
    supersedes_id  TEXT,
    reason         TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS decision_evidence (
    decision_id TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    PRIMARY KEY (decision_id, message_id),
    FOREIGN KEY (decision_id) REFERENCES decisions(id),
    FOREIGN KEY (message_id)  REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id          TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    decision_id TEXT,
    before_json TEXT NOT NULL,
    after_json  TEXT NOT NULL,
    user_text   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_rules (
    id                 TEXT PRIMARY KEY,
    team_id            TEXT NOT NULL,
    project_id         TEXT,
    rule_type          TEXT NOT NULL,
    trigger            TEXT NOT NULL,
    instruction        TEXT NOT NULL,
    scope              TEXT NOT NULL DEFAULT 'team',
    source_feedback_id TEXT,
    source_excerpt     TEXT,
    confidence         REAL NOT NULL DEFAULT 0.5,
    status             TEXT NOT NULL DEFAULT 'candidate',
    created_at         TEXT NOT NULL,
    last_used_at       TEXT,
    use_count          INTEGER NOT NULL DEFAULT 0,
    positive_count     INTEGER NOT NULL DEFAULT 0,
    negative_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                   TEXT PRIMARY KEY,
    team_id              TEXT NOT NULL,
    project_id           TEXT NOT NULL,
    mode                 TEXT NOT NULL DEFAULT 'decisionpatch',
    latency_ms           INTEGER NOT NULL,
    input_tokens         INTEGER NOT NULL DEFAULT 0,
    memory_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens        INTEGER NOT NULL DEFAULT 0,
    memory_hit_count     INTEGER NOT NULL DEFAULT 0,
    memory_applied_count INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_feedback_events (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    original_result TEXT NOT NULL,
    user_text       TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_rules (
    id                 TEXT PRIMARY KEY,
    team_id            TEXT NOT NULL,
    project_id         TEXT NOT NULL,
    rule_type          TEXT NOT NULL,
    title              TEXT NOT NULL,
    subject            TEXT NOT NULL,
    action             TEXT NOT NULL,
    effect             TEXT NOT NULL,
    requirement        TEXT NOT NULL,
    severity           TEXT NOT NULL,
    episode_from       INTEGER,
    episode_to         INTEGER,
    source_feedback_id TEXT,
    source_excerpt     TEXT,
    confidence         REAL NOT NULL,
    status             TEXT NOT NULL,
    version            INTEGER NOT NULL DEFAULT 1,
    supersedes_id      TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_agent_runs (
    id                       TEXT PRIMARY KEY,
    team_id                  TEXT NOT NULL,
    project_id               TEXT NOT NULL,
    task_id                  TEXT NOT NULL,
    latency_ms               REAL NOT NULL,
    model_call_count         INTEGER NOT NULL DEFAULT 0,
    estimated_input_tokens   INTEGER NOT NULL DEFAULT 0,
    estimated_memory_tokens  INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens  INTEGER NOT NULL DEFAULT 0,
    memory_hit_count         INTEGER NOT NULL DEFAULT 0,
    memory_applied_count     INTEGER NOT NULL DEFAULT 0,
    created_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_tool_events (
    run_id          TEXT NOT NULL,
    sequence        INTEGER NOT NULL,
    tool_name       TEXT NOT NULL,
    status          TEXT NOT NULL,
    input_summary   TEXT NOT NULL,
    output_summary  TEXT NOT NULL,
    duration_ms     REAL NOT NULL,
    PRIMARY KEY (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS script_user_validations (
    id                       TEXT PRIMARY KEY,
    team_id                  TEXT NOT NULL,
    project_id               TEXT NOT NULL,
    participant_code         TEXT NOT NULL,
    role                     TEXT NOT NULL,
    scenario_id              TEXT NOT NULL,
    completed_feedback_loop  INTEGER NOT NULL,
    rule_judgment            TEXT NOT NULL,
    explanation_clarity      INTEGER NOT NULL,
    trace_trust              INTEGER NOT NULL,
    would_use                INTEGER NOT NULL,
    duration_seconds         INTEGER,
    comment                  TEXT,
    consent                  INTEGER NOT NULL,
    created_at               TEXT NOT NULL,
    UNIQUE(team_id, project_id, participant_code, scenario_id)
);

CREATE TABLE IF NOT EXISTS script_versions (
    id                TEXT PRIMARY KEY,
    team_id           TEXT NOT NULL,
    project_id        TEXT NOT NULL,
    project_name      TEXT NOT NULL,
    version_label     TEXT NOT NULL,
    episode           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    script_text       TEXT NOT NULL,
    source_kind       TEXT NOT NULL,
    source_name       TEXT,
    content_hash      TEXT NOT NULL,
    parent_version_id TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_project      ON messages(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_project     ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_team        ON decisions(team_id);
CREATE INDEX IF NOT EXISTS idx_memory_rules_team     ON memory_rules(team_id);
CREATE INDEX IF NOT EXISTS idx_memory_rules_status   ON memory_rules(status);
CREATE INDEX IF NOT EXISTS idx_script_rules_scope    ON script_rules(team_id, project_id, status);
CREATE INDEX IF NOT EXISTS idx_script_runs_project   ON script_agent_runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_script_validation_project ON script_user_validations(team_id, project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_script_versions_project ON script_versions(team_id, project_id, created_at);
"""


def _iso(dt: datetime | None) -> str | None:
    """datetime -> ISO 字符串；None 保持 None。"""
    return dt.isoformat() if dt else None


def _parse_iso(s: str | None) -> datetime | None:
    """ISO 字符串 -> datetime；None 保持 None。"""
    return datetime.fromisoformat(s) if s else None


class SQLiteRepository:
    """DecisionPatch 的持久层入口。

    用法：
        repo = SQLiteRepository("decisionpatch.db")
        repo.init()
        repo.create_team(Team(id="team_demo", ...))
    测试用内存库：
        repo = SQLiteRepository(":memory:")
    """

    def __init__(self, path: str = "decisionpatch.db") -> None:
        self._path = path
        # check_same_thread=False：Streamlit 在多线程下访问
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")

    # -- 生命周期 ----------------------------------------------------------- #

    def init(self) -> None:
        """建表 / 迁移。幂等，可重复调用。"""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文：成功提交，异常回滚。"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- teams ------------------------------------------------------------- #

    def create_team(self, *, id: str, name: str, created_at: datetime) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO teams(id, name, created_at) VALUES(?, ?, ?)",
            (id, name, _iso(created_at)),
        )
        self._conn.commit()

    def get_team(self, id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM teams WHERE id = ?", (id,)
        ).fetchone()
        return dict(row) if row else None

    # -- projects ---------------------------------------------------------- #

    def create_project(
        self, *, id: str, team_id: str, name: str, status: str = "open",
        created_at: datetime,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO projects(id, team_id, name, status, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (id, team_id, name, status, _iso(created_at)),
        )
        self._conn.commit()

    def get_project(self, id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (id,)
        ).fetchone()
        return dict(row) if row else None

    # -- messages ---------------------------------------------------------- #

    def insert_messages(self, messages: list[Message]) -> None:
        """批量写入消息（规格 4.1 规范化后落库）。"""
        from datetime import datetime as _dt

        now = _iso(datetime.now())
        rows = [
            (m.id, m.project_id, m.sender, _iso(m.sent_at), m.content,
             m.source_hash, now)
            for m in messages
        ]
        with self.transaction() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO messages"
                "(id, project_id, sender, sent_at, content, source_hash, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def list_messages(self, project_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE project_id = ? ORDER BY sent_at, rowid",
            (project_id,),
        ).fetchall()
        return [
            Message(
                id=r["id"],
                project_id=r["project_id"],
                sender=r["sender"],
                sent_at=_parse_iso(r["sent_at"]),
                content=r["content"],
                source_hash=r["source_hash"],
            )
            for r in rows
        ]

    # -- decisions --------------------------------------------------------- #

    def insert_decision(self, d: DecisionRecord, *, created_at: datetime) -> None:
        """写入决策对象及其证据绑定（规格 5.1 / 7.3）。"""
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decisions"
                "(id, team_id, project_id, type, summary, owner, deadline, "
                " status, confidence, created_by, supersedes_id, reason, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    d.id, d.team_id, d.project_id, d.type.value, d.summary,
                    d.owner, _iso(d.deadline), d.status.value, d.confidence,
                    d.created_by.value, d.supersedes_id, d.reason, _iso(created_at),
                ),
            )
            # 证据多对多（规格 5.3 decision_evidence）
            conn.executemany(
                "INSERT OR IGNORE INTO decision_evidence(decision_id, message_id) "
                "VALUES(?, ?)",
                [(d.id, mid) for mid in d.evidence_message_ids],
            )

    def get_decision(self, id: str) -> DecisionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (id,)
        ).fetchone()
        if not row:
            return None
        ev_rows = self._conn.execute(
            "SELECT message_id FROM decision_evidence WHERE decision_id = ?", (id,)
        ).fetchall()
        return _row_to_decision(row, [r["message_id"] for r in ev_rows])

    def update_decision(self, id: str, **fields) -> None:
        """部分更新决策对象（规格 4.2 用户纠正）。"""
        if not fields:
            return
        # 白名单：只允许更新这些列
        allowed = {
            "type", "summary", "owner", "deadline", "status", "confidence",
            "created_by", "supersedes_id", "reason",
        }
        cols = [(k, v) for k, v in fields.items() if k in allowed]
        if not cols:
            return
        set_clause = ", ".join(f"{k} = ?" for k, _ in cols)
        values = [v if not isinstance(v, datetime) else _iso(v) for _, v in cols]
        # 枚举值取 .value
        values = [v.value if hasattr(v, "value") else v for v in values]
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE decisions SET {set_clause} WHERE id = ?",
                (*values, id),
            )

    def list_decisions(self, project_id: str) -> list[DecisionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        results: list[DecisionRecord] = []
        for r in rows:
            ev = self._conn.execute(
                "SELECT message_id FROM decision_evidence WHERE decision_id = ?",
                (r["id"],),
            ).fetchall()
            results.append(_row_to_decision(r, [e["message_id"] for e in ev]))
        return results

    # -- feedback_events --------------------------------------------------- #

    def insert_feedback_event(self, fb: FeedbackEvent) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO feedback_events"
            "(id, team_id, project_id, decision_id, before_json, after_json, "
            " user_text, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fb.id, fb.team_id, fb.project_id, fb.decision_id,
                fb.before_json, fb.after_json, fb.user_text, _iso(fb.created_at),
            ),
        )
        self._conn.commit()

    def get_feedback_event(self, id: str) -> FeedbackEvent | None:
        row = self._conn.execute(
            "SELECT * FROM feedback_events WHERE id = ?", (id,)
        ).fetchone()
        if not row:
            return None
        return FeedbackEvent(
            id=row["id"],
            team_id=row["team_id"],
            project_id=row["project_id"],
            decision_id=row["decision_id"],
            before_json=row["before_json"],
            after_json=row["after_json"],
            user_text=row["user_text"],
            created_at=_parse_iso(row["created_at"]),
        )

    # -- memory_rules ------------------------------------------------------ #

    def insert_memory_rule(self, rule: MemoryRule) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_rules"
            "(id, team_id, project_id, rule_type, trigger, instruction, scope, "
            " source_feedback_id, source_excerpt, confidence, status, created_at, "
            " last_used_at, use_count, positive_count, negative_count) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule.id, rule.team_id, rule.project_id, rule.rule_type.value,
                rule.trigger, rule.instruction, rule.scope.value,
                rule.source_feedback_id, rule.source_excerpt, rule.confidence,
                rule.status.value, _iso(rule.created_at), _iso(rule.last_used_at),
                rule.use_count, rule.positive_count, rule.negative_count,
            ),
        )
        self._conn.commit()

    def get_memory_rule(self, id: str) -> MemoryRule | None:
        row = self._conn.execute(
            "SELECT * FROM memory_rules WHERE id = ?", (id,)
        ).fetchone()
        return _row_to_memory(row) if row else None

    def update_memory_status(self, id: str, status: MemoryStatus) -> None:
        """记忆生命周期转换（规格 6.5 / 图 3）。"""
        self._conn.execute(
            "UPDATE memory_rules SET status = ? WHERE id = ?",
            (status.value, id),
        )
        self._conn.commit()

    def list_active_memories(
        self,
        *,
        team_id: str,
        project_id: str | None = None,
        rule_types: list[RuleType] | None = None,
    ) -> list[MemoryRule]:
        """硬过滤检索（规格 6.3 第 1 步）。

        按 team_id、active 状态、规则类型过滤；
        project_id 给定时同时返回团队级（project_id IS NULL）与项目级规则。
        跨团队默认禁止使用（规格 6.5）——本方法只查本团队。
        """
        sql = "SELECT * FROM memory_rules WHERE team_id = ? AND status = ?"
        params: list = [team_id, MemoryStatus.active.value]
        if project_id is not None:
            sql += " AND (project_id IS NULL OR project_id = ?)"
            params.append(project_id)
        if rule_types:
            placeholders = ", ".join("?" for _ in rule_types)
            sql += f" AND rule_type IN ({placeholders})"
            params.extend(rt.value for rt in rule_types)
        sql += " ORDER BY confidence DESC, created_at"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def list_memories_by_status(
        self,
        *,
        team_id: str,
        status: MemoryStatus,
        project_id: str | None = None,
    ) -> list[MemoryRule]:
        """按状态查询记忆（候选/暂停/归档等，规格 §6.5）。

        作用域隔离：只查本团队。project_id 给定时同时返回团队级
        （project_id IS NULL）与项目级规则。
        """
        sql = "SELECT * FROM memory_rules WHERE team_id = ? AND status = ?"
        params: list = [team_id, status.value]
        if project_id is not None:
            sql += " AND (project_id IS NULL OR project_id = ?)"
            params.append(project_id)
        sql += " ORDER BY created_at"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def record_memory_use(
        self,
        id: str,
        *,
        positive: bool = False,
        negative: bool = False,
        used_at: datetime,
    ) -> None:
        """记录一次记忆使用与反馈（规格 6.5 负反馈降权）。"""
        self._conn.execute(
            "UPDATE memory_rules SET use_count = use_count + 1, "
            "last_used_at = ?, "
            "positive_count = positive_count + ?, "
            "negative_count = negative_count + ? WHERE id = ?",
            (
                _iso(used_at),
                1 if positive else 0,
                1 if negative else 0,
                id,
            ),
        )
        self._conn.commit()

    # -- agent_runs -------------------------------------------------------- #

    def insert_agent_run(self, run: AgentRun) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO agent_runs"
            "(id, team_id, project_id, mode, latency_ms, input_tokens, "
            " memory_tokens, output_tokens, memory_hit_count, "
            " memory_applied_count, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id, run.team_id, run.project_id, run.mode.value,
                run.latency_ms, run.input_tokens, run.memory_tokens,
                run.output_tokens, run.memory_hit_count,
                run.memory_applied_count, _iso(run.created_at),
            ),
        )
        self._conn.commit()

    def list_agent_runs(self, project_id: str) -> list[AgentRun]:
        rows = self._conn.execute(
            "SELECT * FROM agent_runs WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            AgentRun(
                id=r["id"],
                team_id=r["team_id"],
                project_id=r["project_id"],
                mode=r["mode"],
                latency_ms=r["latency_ms"],
                input_tokens=r["input_tokens"],
                memory_tokens=r["memory_tokens"],
                output_tokens=r["output_tokens"],
                memory_hit_count=r["memory_hit_count"],
                memory_applied_count=r["memory_applied_count"],
                created_at=_parse_iso(r["created_at"]),
            )
            for r in rows
        ]

    # -- ScriptLint：反馈、规则与工具轨迹 ------------------------------- #

    def insert_script_version(self, version: ScriptVersion) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO script_versions"
            "(id, team_id, project_id, project_name, version_label, episode, title, "
            " script_text, source_kind, source_name, content_hash, parent_version_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version.id,
                version.team_id,
                version.project_id,
                version.project_name,
                version.version_label,
                version.episode,
                version.title,
                version.script_text,
                version.source_kind.value,
                version.source_name,
                version.content_hash,
                version.parent_version_id,
                _iso(version.created_at),
            ),
        )
        self._conn.commit()

    def get_script_version(self, id: str) -> ScriptVersion | None:
        row = self._conn.execute(
            "SELECT * FROM script_versions WHERE id = ?", (id,)
        ).fetchone()
        return _row_to_script_version(row) if row else None

    def list_script_versions(
        self, *, team_id: str, project_id: str
    ) -> list[ScriptVersion]:
        rows = self._conn.execute(
            "SELECT * FROM script_versions WHERE team_id = ? AND project_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (team_id, project_id),
        ).fetchall()
        return [_row_to_script_version(row) for row in rows]

    def insert_script_feedback(self, feedback: ScriptFeedbackEvent) -> None:
        self._conn.execute(
            "INSERT INTO script_feedback_events"
            "(id, team_id, project_id, original_result, user_text, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                feedback.id,
                feedback.team_id,
                feedback.project_id,
                feedback.original_result,
                feedback.user_text,
                _iso(feedback.created_at),
            ),
        )
        self._conn.commit()

    def get_script_feedback(self, id: str) -> ScriptFeedbackEvent | None:
        row = self._conn.execute(
            "SELECT * FROM script_feedback_events WHERE id = ?", (id,)
        ).fetchone()
        if not row:
            return None
        return ScriptFeedbackEvent(
            id=row["id"],
            team_id=row["team_id"],
            project_id=row["project_id"],
            original_result=row["original_result"],
            user_text=row["user_text"],
            created_at=_parse_iso(row["created_at"]),
        )

    def insert_script_rule(self, rule: ScriptRule) -> None:
        if rule.created_at is None:
            raise ValueError("持久化 ScriptRule 前必须设置 created_at")
        self._conn.execute(
            "INSERT INTO script_rules"
            "(id, team_id, project_id, rule_type, title, subject, action, effect, "
            " requirement, severity, episode_from, episode_to, source_feedback_id, "
            " source_excerpt, confidence, status, version, supersedes_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule.id,
                rule.team_id,
                rule.project_id,
                rule.rule_type.value,
                rule.title,
                rule.subject,
                rule.action,
                rule.effect.value,
                rule.requirement,
                rule.severity.value,
                rule.episode_from,
                rule.episode_to,
                rule.source_feedback_id,
                rule.source_excerpt,
                rule.confidence,
                rule.status.value,
                rule.version,
                rule.supersedes_id,
                _iso(rule.created_at),
            ),
        )
        self._conn.commit()

    def get_script_rule(self, id: str) -> ScriptRule | None:
        row = self._conn.execute(
            "SELECT * FROM script_rules WHERE id = ?", (id,)
        ).fetchone()
        return _row_to_script_rule(row) if row else None

    def update_script_rule_status(self, id: str, status: ScriptRuleStatus) -> None:
        self._conn.execute(
            "UPDATE script_rules SET status = ? WHERE id = ?", (status.value, id)
        )
        self._conn.commit()

    def list_script_rules(
        self,
        *,
        team_id: str,
        project_id: str,
        status: ScriptRuleStatus | None = None,
    ) -> list[ScriptRule]:
        sql = "SELECT * FROM script_rules WHERE team_id = ? AND project_id = ?"
        params: list = [team_id, project_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY confidence DESC, created_at, id"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_script_rule(row) for row in rows]

    def insert_script_agent_result(
        self,
        result: ScriptAgentResult,
        *,
        created_at: datetime,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO script_agent_runs"
                "(id, team_id, project_id, task_id, latency_ms, model_call_count, "
                " estimated_input_tokens, estimated_memory_tokens, "
                " estimated_output_tokens, memory_hit_count, memory_applied_count, "
                " created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.run_id,
                    result.task.team_id,
                    result.task.project_id,
                    result.task.id,
                    result.metrics.latency_ms,
                    result.metrics.model_call_count,
                    result.metrics.estimated_input_tokens,
                    result.metrics.estimated_memory_tokens,
                    result.metrics.estimated_output_tokens,
                    result.metrics.memory_hit_count,
                    result.metrics.memory_applied_count,
                    _iso(created_at),
                ),
            )
            conn.execute("DELETE FROM script_tool_events WHERE run_id = ?", (result.run_id,))
            conn.executemany(
                "INSERT INTO script_tool_events"
                "(run_id, sequence, tool_name, status, input_summary, output_summary, duration_ms) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        result.run_id,
                        trace.sequence,
                        trace.tool_name,
                        trace.status.value,
                        trace.input_summary,
                        trace.output_summary,
                        trace.duration_ms,
                    )
                    for trace in result.tool_traces
                ],
            )

    def list_script_tool_traces(self, run_id: str) -> list[ScriptToolTrace]:
        rows = self._conn.execute(
            "SELECT * FROM script_tool_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        return [
            ScriptToolTrace(
                sequence=row["sequence"],
                tool_name=row["tool_name"],
                status=ScriptToolStatus(row["status"]),
                input_summary=row["input_summary"],
                output_summary=row["output_summary"],
                duration_ms=row["duration_ms"],
            )
            for row in rows
        ]

    def insert_script_validation(self, item: ScriptUserValidation) -> None:
        self._conn.execute(
            "INSERT INTO script_user_validations"
            "(id, team_id, project_id, participant_code, role, scenario_id, "
            " completed_feedback_loop, rule_judgment, explanation_clarity, "
            " trace_trust, would_use, duration_seconds, comment, consent, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.team_id,
                item.project_id,
                item.participant_code,
                item.role.value,
                item.scenario_id,
                int(item.completed_feedback_loop),
                item.rule_judgment.value,
                item.explanation_clarity,
                item.trace_trust,
                int(item.would_use),
                item.duration_seconds,
                item.comment,
                int(item.consent),
                _iso(item.created_at),
            ),
        )
        self._conn.commit()

    def list_script_validations(
        self,
        *,
        team_id: str,
        project_id: str,
    ) -> list[ScriptUserValidation]:
        rows = self._conn.execute(
            "SELECT * FROM script_user_validations "
            "WHERE team_id = ? AND project_id = ? ORDER BY created_at, participant_code",
            (team_id, project_id),
        ).fetchall()
        return [
            ScriptUserValidation(
                id=row["id"],
                team_id=row["team_id"],
                project_id=row["project_id"],
                participant_code=row["participant_code"],
                role=ValidationRole(row["role"]),
                scenario_id=row["scenario_id"],
                completed_feedback_loop=bool(row["completed_feedback_loop"]),
                rule_judgment=ValidationJudgment(row["rule_judgment"]),
                explanation_clarity=row["explanation_clarity"],
                trace_trust=row["trace_trust"],
                would_use=bool(row["would_use"]),
                duration_seconds=row["duration_seconds"],
                comment=row["comment"],
                consent=bool(row["consent"]),
                created_at=_parse_iso(row["created_at"]),
            )
            for row in rows
        ]


# --------------------------------------------------------------------------- #
# 行 -> 模型 转换辅助
# --------------------------------------------------------------------------- #

def _row_to_script_version(row: sqlite3.Row) -> ScriptVersion:
    return ScriptVersion(
        id=row["id"],
        team_id=row["team_id"],
        project_id=row["project_id"],
        project_name=row["project_name"],
        version_label=row["version_label"],
        episode=row["episode"],
        title=row["title"],
        script_text=row["script_text"],
        source_kind=ScriptSourceKind(row["source_kind"]),
        source_name=row["source_name"],
        content_hash=row["content_hash"],
        parent_version_id=row["parent_version_id"],
        created_at=_parse_iso(row["created_at"]),
    )

def _row_to_decision(row: sqlite3.Row, evidence_ids: list[str]) -> DecisionRecord:
    from schemas import CreatedBy, DecisionStatus, DecisionType

    return DecisionRecord(
        id=row["id"],
        team_id=row["team_id"],
        project_id=row["project_id"],
        type=DecisionType(row["type"]),
        summary=row["summary"],
        owner=row["owner"],
        deadline=_parse_iso(row["deadline"]),
        status=DecisionStatus(row["status"]),
        confidence=row["confidence"],
        created_by=CreatedBy(row["created_by"]),
        supersedes_id=row["supersedes_id"],
        reason=row["reason"],
        evidence_message_ids=evidence_ids,
    )


def _row_to_memory(row: sqlite3.Row) -> MemoryRule:
    return MemoryRule(
        id=row["id"],
        team_id=row["team_id"],
        project_id=row["project_id"],
        rule_type=RuleType(row["rule_type"]),
        trigger=row["trigger"],
        instruction=row["instruction"],
        scope=MemoryScope(row["scope"]),
        source_feedback_id=row["source_feedback_id"],
        source_excerpt=row["source_excerpt"],
        confidence=row["confidence"],
        status=MemoryStatus(row["status"]),
        created_at=_parse_iso(row["created_at"]),
        last_used_at=_parse_iso(row["last_used_at"]),
        use_count=row["use_count"],
        positive_count=row["positive_count"],
        negative_count=row["negative_count"],
    )


def _row_to_script_rule(row: sqlite3.Row) -> ScriptRule:
    return ScriptRule(
        id=row["id"],
        team_id=row["team_id"],
        project_id=row["project_id"],
        rule_type=ScriptRuleType(row["rule_type"]),
        title=row["title"],
        subject=row["subject"],
        action=row["action"],
        effect=ScriptRuleEffect(row["effect"]),
        requirement=row["requirement"],
        severity=ScriptRuleSeverity(row["severity"]),
        episode_from=row["episode_from"],
        episode_to=row["episode_to"],
        source_feedback_id=row["source_feedback_id"],
        source_excerpt=row["source_excerpt"],
        confidence=row["confidence"],
        status=ScriptRuleStatus(row["status"]),
        version=row["version"],
        supersedes_id=row["supersedes_id"],
        created_at=_parse_iso(row["created_at"]),
    )
