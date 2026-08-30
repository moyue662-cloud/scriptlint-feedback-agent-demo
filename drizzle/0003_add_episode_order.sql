ALTER TABLE scene_states
ADD COLUMN episode_number INTEGER NOT NULL DEFAULT 1;

ALTER TABLE scene_states
ADD COLUMN scene_order INTEGER NOT NULL DEFAULT 0;

UPDATE scene_states
SET scene_order = scene_number
WHERE scene_order = 0;

CREATE INDEX IF NOT EXISTS idx_scene_states_project_order
ON scene_states(project_id, scene_order, scene_number);
