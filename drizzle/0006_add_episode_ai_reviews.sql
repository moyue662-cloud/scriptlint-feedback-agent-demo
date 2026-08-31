CREATE TABLE IF NOT EXISTS episode_ai_reviews (
  project_id TEXT NOT NULL DEFAULT 'default',
  episode_number INTEGER NOT NULL,
  source_hash TEXT NOT NULL,
  review_json TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  PRIMARY KEY (project_id, episode_number)
);
