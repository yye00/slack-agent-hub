-- Migration 002: add human-readable name column to sessions
ALTER TABLE sessions ADD COLUMN name TEXT;
