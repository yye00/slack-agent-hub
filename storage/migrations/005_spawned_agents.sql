-- Persist dynamically spawned agent configs so they survive hub restarts.
ALTER TABLE agents ADD COLUMN config_json TEXT;
ALTER TABLE agents ADD COLUMN spawned INTEGER DEFAULT 0;
