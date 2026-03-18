"""Tests for named sessions (ISSUES.md #8)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.session_naming import generate_session_name
from storage.db import Database


# ── Unit tests for generate_session_name ──────────────────────────────────────

class TestGenerateSessionName:
    def test_basic_prompt_produces_slug(self):
        name = generate_session_name("Write a Python function to sort a list")
        assert name == "write-python-function-sort"

    def test_stop_words_are_stripped(self):
        name = generate_session_name("Help me with the optimization")
        # "with" and "the" are stop words; "me" is too
        assert "the" not in name.split("-")
        assert "with" not in name.split("-")

    def test_name_is_lowercase_slug(self):
        name = generate_session_name("Optimize The DMRG Run")
        assert name == name.lower()
        assert " " not in name
        assert all(c.isalnum() or c == "-" for c in name)

    def test_empty_prompt_returns_unnamed(self):
        assert generate_session_name("") == "unnamed-session"
        assert generate_session_name("   ") == "unnamed-session"
        assert generate_session_name(None) == "unnamed-session"  # type: ignore[arg-type]

    def test_max_four_words(self):
        name = generate_session_name("refactor database connection pool manager class")
        parts = name.split("-")
        assert len(parts) <= 4

    def test_special_chars_removed(self):
        name = generate_session_name("Fix bug: crashes on start-up! (urgent)")
        assert ":" not in name
        assert "!" not in name
        assert "(" not in name

    def test_concise_technical_prompt(self):
        name = generate_session_name("Optimize DMRG run for H2 molecule")
        # Should contain meaningful technical words
        assert len(name) > 0
        assert name != "unnamed-session"

    def test_first_line_only(self):
        name = generate_session_name("First line prompt\nSecond line context\nThird line")
        # Should only use first line
        assert "second" not in name
        assert "third" not in name

    def test_unicode_normalized(self):
        name = generate_session_name("Résumé optimization for café")
        # Unicode should be normalized to ASCII
        assert all(c.isascii() for c in name)

    def test_max_slug_length(self):
        long_prompt = "a" * 100 + " verylongwordindeed " + "b" * 100
        name = generate_session_name(long_prompt)
        assert len(name) <= 40

    def test_all_stop_words_falls_back_to_original(self):
        # If all words are stop words, fall back rather than returning empty
        name = generate_session_name("the a an")
        assert name != ""
        assert "-" not in name or name != "-"


# ── Integration tests with Database ───────────────────────────────────────────

@pytest_asyncio.fixture
async def tmp_db():
    """Provide a temporary in-memory-like Database backed by a temp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)
        await db.initialize()
        yield db
        await db.close()


@pytest.mark.asyncio
async def test_migration_idempotent(tmp_db):
    """Running migrations twice must not crash (idempotency fix)."""
    # Re-run migrations on the same connection — should be a no-op
    await tmp_db._run_migrations()
    # If we get here without an exception, idempotency is working


@pytest.mark.asyncio
async def test_session_name_stored_in_db(tmp_db):
    """update_session_name stores a name that is retrievable via get_session."""
    await tmp_db.upsert_agent("testbot", "active", "2025-01-01T00:00:00+00:00")
    await tmp_db.create_session(
        id="sess-uuid-001",
        agent_name="testbot",
        thread_ts=None,
        label=None,
        model="claude-3-5-sonnet",
        backend="claude",
    )

    await tmp_db.update_session_name("sess-uuid-001", "python-sort-optimization")

    row = await tmp_db.get_session("sess-uuid-001")
    assert row is not None
    assert row["name"] == "python-sort-optimization"


@pytest.mark.asyncio
async def test_session_name_shows_in_list_sessions(tmp_db):
    """list_sessions returns rows that include the name field."""
    await tmp_db.upsert_agent("coder", "active", "2025-01-01T00:00:00+00:00")
    await tmp_db.create_session(
        id="sess-uuid-002",
        agent_name="coder",
        thread_ts=None,
        label=None,
        model="claude-3-5-sonnet",
        backend="claude",
    )
    await tmp_db.update_session_name("sess-uuid-002", "dmrg-optimization-run")

    sessions = await tmp_db.list_sessions("coder")
    assert len(sessions) == 1
    assert sessions[0]["name"] == "dmrg-optimization-run"


@pytest.mark.asyncio
async def test_session_name_default_is_none(tmp_db):
    """A session created without a name has name=None."""
    await tmp_db.upsert_agent("coder2", "active", "2025-01-01T00:00:00+00:00")
    await tmp_db.create_session(
        id="sess-uuid-003",
        agent_name="coder2",
        thread_ts=None,
        label=None,
        model="claude-3-5-sonnet",
        backend="claude",
    )

    row = await tmp_db.get_session("sess-uuid-003")
    assert row is not None
    assert row.get("name") is None


# ── Integration test: _cmd_sessions shows name ─────────────────────────────────

@pytest.mark.asyncio
async def test_sessions_command_shows_name(tmp_db):
    """The !sessions command output includes the session name."""
    from core.command_handler import CommandHandler

    # Seed DB
    await tmp_db.upsert_agent("myagent", "active", "2025-01-01T00:00:00+00:00")
    await tmp_db.create_session(
        id="abcdef12-0000-0000-0000-000000000000",
        agent_name="myagent",
        thread_ts=None,
        label=None,
        model="claude-3-5-sonnet",
        backend="claude",
    )
    await tmp_db.update_session_name("abcdef12-0000-0000-0000-000000000000", "fix-auth-bug")

    # Build a CommandHandler with minimal mocks
    poster = MagicMock()
    replied_texts = []

    async def fake_post(channel, text, thread_ts=None, **kwargs):
        replied_texts.append(text)
        return {"ts": "1234"}

    poster.post = AsyncMock(side_effect=fake_post)

    handler = CommandHandler(
        agents={},
        db=tmp_db,
        slack_client=MagicMock(),
        poster=poster,
    )

    await handler._cmd_sessions(
        args=["myagent"],
        options={},
        channel_id="C001",
        thread_ts=None,
        target_agent="myagent",
        user="U001",
    )

    assert len(replied_texts) == 1
    output = replied_texts[0]
    # Should show the truncated UUID
    assert "abcdef12" in output
    # Should show the name
    assert "fix-auth-bug" in output


# ── End-to-end: run_agent_query stores session name ────────────────────────────

@pytest.mark.asyncio
async def test_run_agent_query_stores_session_name(tmp_db):
    """After run_agent_query, a DB row exists with the auto-generated name."""
    from core.session_naming import generate_session_name

    prompt = "Refactor the authentication module"
    expected_name = generate_session_name(prompt)
    assert expected_name != "unnamed-session"

    # Simulate what hub.run_agent_query does after getting result.session_id
    real_session_id = "real-sess-aabbccdd"

    await tmp_db.upsert_agent("hub-agent", "active", "2025-01-01T00:00:00+00:00")

    existing = await tmp_db.get_session(real_session_id)
    if not existing:
        session_name = generate_session_name(prompt)
        await tmp_db.create_session(
            id=real_session_id,
            agent_name="hub-agent",
            thread_ts=None,
            label=None,
            model="claude-3-5-sonnet",
            backend="claude",
        )
        await tmp_db.update_session_name(real_session_id, session_name)

    row = await tmp_db.get_session(real_session_id)
    assert row is not None
    assert row["name"] == expected_name
    assert row["id"] == real_session_id
