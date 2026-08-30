export const createSceneStatesTableSql = `CREATE TABLE IF NOT EXISTS scene_states (
  id TEXT PRIMARY KEY,
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
