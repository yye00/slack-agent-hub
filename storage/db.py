"""SQLite storage layer with migration support."""

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self):
        """Open connection and run migrations."""
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._run_migrations()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def _run_migrations(self):
        """Run SQL migration files in order, skipping already-applied ones."""
        # Ensure registry table exists before we try to track migrations in it
        await self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS registry (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for mf in migration_files:
            key = f"migration:{mf.name}"
            cursor = await self._conn.execute(
                "SELECT value FROM registry WHERE key=?", (key,)
            )
            row = await cursor.fetchone()
            if row:
                continue  # Already applied

            sql = mf.read_text()
            await self._conn.executescript(sql)

            timestamp = datetime.now(timezone.utc).isoformat()
            await self._conn.execute(
                "INSERT INTO registry (key, value) VALUES (?, ?)",
                (key, timestamp),
            )
            await self._conn.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Generic query helpers ──

    async def fetch_one(self, sql: str, params=()) -> dict | None:
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params=()) -> list[dict]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def execute(self, sql: str, params=()):
        await self._conn.execute(sql, params)
        await self._conn.commit()

    # ── Agents ──

    async def upsert_agent(self, name: str, status: str, started_at: str):
        await self.execute(
            "INSERT INTO agents (name, status, started_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET status=?, started_at=?",
            (name, status, started_at, status, started_at),
        )

    async def get_agent(self, name: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM agents WHERE name=?", (name,))

    async def list_agents(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM agents ORDER BY name")

    async def update_agent_status(self, name: str, status: str):
        await self.execute("UPDATE agents SET status=? WHERE name=?", (status, name))

    async def update_agent_last_active(self, name: str):
        await self.execute(
            "UPDATE agents SET last_active=? WHERE name=?", (self._now(), name)
        )

    # ── Sessions ──

    async def create_session(
        self,
        id: str,
        agent_name: str,
        thread_ts: str | None,
        label: str | None,
        model: str,
        backend: str,
    ):
        await self.execute(
            "INSERT INTO sessions (id, agent_name, thread_ts, label, model, backend, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, agent_name, thread_ts, label, model, backend, self._now()),
        )

    async def get_session(self, id: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM sessions WHERE id=?", (id,))

    async def list_sessions(self, agent_name: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM sessions WHERE agent_name=? AND archived=0 ORDER BY created_at DESC",
            (agent_name,),
        )

    async def archive_session(self, id: str, reason: str):
        await self.execute(
            "UPDATE sessions SET archived=1, archive_reason=? WHERE id=?",
            (reason, id),
        )

    async def update_session_last_active(self, id: str):
        await self.execute(
            "UPDATE sessions SET last_active=? WHERE id=?", (self._now(), id)
        )

    async def update_session_name(self, id: str, name: str):
        await self.execute(
            "UPDATE sessions SET name=? WHERE id=?", (name, id)
        )

    async def save_session_summary(self, id: str, summary: str, ended_cleanly: bool):
        await self.execute(
            "UPDATE sessions SET summary=?, ended_cleanly=? WHERE id=?",
            (summary, 1 if ended_cleanly else 0, id),
        )

    async def get_previous_session(self, agent_name: str, exclude_id: str = "") -> dict | None:
        """Get the most recent session for an agent, excluding the current one."""
        return await self.fetch_one(
            "SELECT * FROM sessions WHERE agent_name=? AND id != ? AND archived=0 "
            "ORDER BY created_at DESC LIMIT 1",
            (agent_name, exclude_id),
        )

    # ── Pins ──

    async def create_pin(self, channel_id: str, content: str, pinned_by: str | None):
        await self.execute(
            "INSERT INTO pins (channel_id, content, pinned_by, created_at) VALUES (?, ?, ?, ?)",
            (channel_id, content, pinned_by, self._now()),
        )

    async def list_pins(self, channel_id: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM pins WHERE channel_id=? ORDER BY created_at", (channel_id,)
        )

    async def delete_pin(self, pin_id: int):
        await self.execute("DELETE FROM pins WHERE id=?", (pin_id,))

    # ── Cost ──

    async def log_cost(
        self,
        agent_name: str,
        session_id: str | None,
        input_tokens: int,
        output_tokens: int,
        model: str | None,
    ):
        await self.execute(
            "INSERT INTO cost_log (agent_name, session_id, input_tokens, output_tokens, model, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_name, session_id, input_tokens, output_tokens, model, self._now()),
        )

    async def get_agent_costs(self, agent_name: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM cost_log WHERE agent_name=? ORDER BY timestamp",
            (agent_name,),
        )

    # ── Registry KV ──

    async def set_registry(self, key: str, value: str):
        await self.execute(
            "INSERT INTO registry (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=?",
            (key, value, value),
        )

    async def get_registry(self, key: str) -> str | None:
        row = await self.fetch_one("SELECT value FROM registry WHERE key=?", (key,))
        return row["value"] if row else None
