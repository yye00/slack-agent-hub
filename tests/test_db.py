import pytest
import pytest_asyncio
import aiosqlite

from storage.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_initialize_creates_tables(db):
    """All tables from the schema should exist after init."""
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "agents" in table_names
    assert "sessions" in table_names
    assert "pins" in table_names
    assert "monitors" in table_names
    assert "cost_log" in table_names
    assert "message_index" in table_names
    assert "scheduled" in table_names
    assert "registry" in table_names


@pytest.mark.asyncio
async def test_agent_upsert_and_get(db):
    await db.upsert_agent("fred", "active", "2026-03-13T10:00:00Z")
    agent = await db.get_agent("fred")
    assert agent["name"] == "fred"
    assert agent["status"] == "active"


@pytest.mark.asyncio
async def test_agent_update_status(db):
    await db.upsert_agent("fred", "active", "2026-03-13T10:00:00Z")
    await db.update_agent_status("fred", "paused")
    agent = await db.get_agent("fred")
    assert agent["status"] == "paused"


@pytest.mark.asyncio
async def test_session_create_and_list(db):
    await db.upsert_agent("fred", "active", "2026-03-13T10:00:00Z")
    await db.create_session(
        id="cc4e3ea8",
        agent_name="fred",
        thread_ts=None,
        label="hotfix",
        model="claude-sonnet-4-5",
        backend="claude",
    )
    sessions = await db.list_sessions("fred")
    assert len(sessions) == 1
    assert sessions[0]["id"] == "cc4e3ea8"
    assert sessions[0]["label"] == "hotfix"


@pytest.mark.asyncio
async def test_session_archive(db):
    await db.upsert_agent("fred", "active", "2026-03-13T10:00:00Z")
    await db.create_session(
        id="cc4e3ea8",
        agent_name="fred",
        thread_ts=None,
        label=None,
        model="claude-sonnet-4-5",
        backend="claude",
    )
    await db.archive_session("cc4e3ea8", reason="stale")
    session = await db.get_session("cc4e3ea8")
    assert session["archived"] == 1
    assert session["archive_reason"] == "stale"


@pytest.mark.asyncio
async def test_pin_create_and_list(db):
    await db.create_pin("C123", "Always use Poetry", "U456")
    pins = await db.list_pins("C123")
    assert len(pins) == 1
    assert pins[0]["content"] == "Always use Poetry"


@pytest.mark.asyncio
async def test_pin_delete(db):
    await db.create_pin("C123", "note1", "U456")
    pins = await db.list_pins("C123")
    await db.delete_pin(pins[0]["id"])
    pins = await db.list_pins("C123")
    assert len(pins) == 0


@pytest.mark.asyncio
async def test_cost_log(db):
    await db.log_cost("fred", "sess1", 1000, 500, "claude-sonnet-4-5")
    await db.log_cost("fred", "sess1", 2000, 800, "claude-sonnet-4-5")
    costs = await db.get_agent_costs("fred")
    assert len(costs) == 2
    total_in = sum(c["input_tokens"] for c in costs)
    assert total_in == 3000


@pytest.mark.asyncio
async def test_registry_kv(db):
    await db.set_registry("registry_message_ts", "1710340920.123456")
    val = await db.get_registry("registry_message_ts")
    assert val == "1710340920.123456"


@pytest.mark.asyncio
async def test_registry_kv_missing_key(db):
    val = await db.get_registry("nonexistent")
    assert val is None
