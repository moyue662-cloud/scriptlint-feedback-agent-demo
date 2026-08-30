CREATE TABLE IF NOT EXISTS episode_summaries (
  project_id TEXT NOT NULL DEFAULT 'default',
  episode_number INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  objective TEXT NOT NULL DEFAULT '',
  conflict TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (project_id, episode_number)
);
