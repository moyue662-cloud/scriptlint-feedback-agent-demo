ALTER TABLE scene_states
ADD COLUMN delivery_tracking_json TEXT NOT NULL DEFAULT '{}';
