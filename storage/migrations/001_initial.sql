CREATE TABLE IF NOT EXISTS agents (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'active',
    started_at  TEXT NOT NULL,
    last_active TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    agent_name     TEXT NOT NULL REFERENCES agents(name),
    thread_ts      TEXT,
    label          TEXT,
    model          TEXT,
    backend        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_active    TEXT,
    archived       INTEGER NOT NULL DEFAULT 0,
    archive_reason TEXT
);

CREATE TABLE IF NOT EXISTS pins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    content    TEXT NOT NULL,
    pinned_by  TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitors (
    id         TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL REFERENCES agents(name),
    type       TEXT NOT NULL,
    target     TEXT NOT NULL,
    poll_secs  INTEGER NOT NULL DEFAULT 30,
    last_offset INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name    TEXT NOT NULL,
    session_id    TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    model         TEXT,
    timestamp     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_index (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    host_id    TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    thread_ts  TEXT,
    message_ts TEXT NOT NULL,
    content    TEXT NOT NULL,
    topics     TEXT,
    timestamp  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL REFERENCES agents(name),
    command    TEXT NOT NULL,
    cron_expr  TEXT NOT NULL,
    last_run   TEXT,
    next_run   TEXT,
    enabled    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS registry (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
