ALTER TABLE projects
ADD COLUMN archived_at TEXT;

CREATE INDEX IF NOT EXISTS idx_projects_archived_updated
ON projects(archived_at, updated_at DESC);

PRAGMA optimize;
