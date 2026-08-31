CREATE TABLE IF NOT EXISTS scene_visual_reviews (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT 'default',
  scene_id TEXT,
  source_name TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  review_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scene_visual_reviews_project_scene
  ON scene_visual_reviews(project_id, scene_id, created_at DESC);
