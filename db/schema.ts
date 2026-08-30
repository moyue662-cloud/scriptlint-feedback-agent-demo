export const createProjectsTableSql = `CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)`;

export const createSceneStatesTableSql = `CREATE TABLE IF NOT EXISTS scene_states (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT 'default',
  scene_number INTEGER NOT NULL UNIQUE,
  title TEXT NOT NULL,
  source_hash TEXT NOT NULL UNIQUE,
  script TEXT NOT NULL,
  analysis_json TEXT NOT NULL,
  storyboard_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  delivery_tracking_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
)`;
