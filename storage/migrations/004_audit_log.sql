CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    action     TEXT NOT NULL,
    target     TEXT,
    channel_id TEXT,
    detail     TEXT,
    timestamp  TEXT NOT NULL
);
