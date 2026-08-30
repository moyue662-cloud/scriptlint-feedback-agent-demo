CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

ALTER TABLE scene_states
ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default';

INSERT OR IGNORE INTO projects (id, name, created_at, updated_at)
VALUES ('default', '未命名短剧项目', datetime('now'), datetime('now'));
