CREATE TABLE IF NOT EXISTS scene_versions (
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
);

CREATE INDEX IF NOT EXISTS idx_scene_versions_project_scene
  ON scene_versions(project_id, scene_id, version_number DESC);

INSERT OR IGNORE INTO scene_versions
  (id, scene_id, project_id, version_number, episode_number, title, source_hash, script, analysis_json, storyboard_json, snapshot_json, delivery_tracking_json, created_at)
SELECT 'baseline:' || s.id, s.id, s.project_id, 1, s.episode_number, s.title, s.source_hash, s.script,
  s.analysis_json, s.storyboard_json, s.snapshot_json, s.delivery_tracking_json, s.created_at
FROM scene_states s
WHERE NOT EXISTS (
  SELECT 1 FROM scene_versions v WHERE v.scene_id = s.id AND v.project_id = s.project_id
);
