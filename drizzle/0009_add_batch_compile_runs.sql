ALTER TABLE scene_states
ADD COLUMN batch_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_states_project_batch_key
ON scene_states(project_id, batch_key)
WHERE batch_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS batch_compile_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'active',
  drafts_json TEXT NOT NULL,
  items_json TEXT NOT NULL,
  adaptation_json TEXT,
  next_index INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_compile_runs_project_status
ON batch_compile_runs(project_id, status, updated_at DESC);

PRAGMA optimize;
