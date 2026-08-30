export const createProjectsTableSql = `CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  approved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)`;

export const createEpisodeSummariesTableSql = `CREATE TABLE IF NOT EXISTS episode_summaries (
  project_id TEXT NOT NULL DEFAULT 'default',
  episode_number INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  objective TEXT NOT NULL DEFAULT '',
  conflict TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (project_id, episode_number)
)`;

export const createSceneStatesTableSql = `CREATE TABLE IF NOT EXISTS scene_states (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT 'default',
  scene_number INTEGER NOT NULL UNIQUE,
  episode_number INTEGER NOT NULL DEFAULT 1,
  scene_order INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL,
  source_hash TEXT NOT NULL UNIQUE,
  script TEXT NOT NULL,
  analysis_json TEXT NOT NULL,
  storyboard_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  delivery_tracking_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
)`;

export const createSceneOrderIndexSql = `CREATE INDEX IF NOT EXISTS idx_scene_states_project_order
  ON scene_states(project_id, scene_order, scene_number)`;
