-- Migration 003: add session summary and clean-shutdown flag to sessions
ALTER TABLE sessions ADD COLUMN summary TEXT;
ALTER TABLE sessions ADD COLUMN ended_cleanly INTEGER;
