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

export const createEpisodeAiReviewsTableSql = `CREATE TABLE IF NOT EXISTS episode_ai_reviews (
  project_id TEXT NOT NULL DEFAULT 'default',
  episode_number INTEGER NOT NULL,
  source_hash TEXT NOT NULL,
  review_json TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
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
  batch_key TEXT,
  created_at TEXT NOT NULL
)`;

export const createSceneOrderIndexSql = `CREATE INDEX IF NOT EXISTS idx_scene_states_project_order
  ON scene_states(project_id, scene_order, scene_number)`;

export const createSceneBatchKeyIndexSql = `CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_states_project_batch_key
  ON scene_states(project_id, batch_key) WHERE batch_key IS NOT NULL`;

export const createBatchCompileRunsTableSql = `CREATE TABLE IF NOT EXISTS batch_compile_runs (
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
)`;

export const createBatchCompileRunsIndexSql = `CREATE INDEX IF NOT EXISTS idx_batch_compile_runs_project_status
  ON batch_compile_runs(project_id, status, updated_at DESC)`;

export const createSceneVersionsTableSql = `CREATE TABLE IF NOT EXISTS scene_versions (
  id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT 'default',
  version_number INTEGER NOT NULL,
  episode_number INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  script TEXT NOT NULL,
  analysis_json TEXT NOT NULL,
  storyboard_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  delivery_tracking_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(scene_id, version_number)
)`;

export const createSceneVersionsIndexSql = `CREATE INDEX IF NOT EXISTS idx_scene_versions_project_scene
  ON scene_versions(project_id, scene_id, version_number DESC)`;

export const createSceneVisualReviewsTableSql = `CREATE TABLE IF NOT EXISTS scene_visual_reviews (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT 'default',
  scene_id TEXT,
  source_name TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  review_json TEXT NOT NULL,
  created_at TEXT NOT NULL
)`;

export const createSceneVisualReviewsIndexSql = `CREATE INDEX IF NOT EXISTS idx_scene_visual_reviews_project_scene
  ON scene_visual_reviews(project_id, scene_id, created_at DESC)`;
