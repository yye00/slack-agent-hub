"""Tests for !export, !import, and !fork session commands."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from core.command_handler import CommandHandler


@pytest.fixture
def handler():
    agents = {
        "fred": MagicMock(
            name="fred",
            display_name="Fred",
            backend=MagicMock(name="claude"),
            config=MagicMock(model="claude-sonnet-4-5", profile="dev", cwd="/tmp/test"),
            status="active",
            current_session_id=None,
            _active_query_task=None,
        ),
    }
    db = AsyncMock()
    slack_client = AsyncMock()
    poster = AsyncMock()
    poster.post = AsyncMock()
    return CommandHandler(agents=agents, db=db, slack_client=slack_client, poster=poster)


def _reply_text(handler):
    """Get the text from the most recent _reply call."""
    return handler._poster.post.call_args.kwargs["text"]


# ── !export ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_no_args(handler):
    await handler.handle("export", [], {}, "C1", None, "fred", "U1")
    assert "Usage" in _reply_text(handler)


@pytest.mark.asyncio
async def test_export_session_not_found(handler):
    handler._db.get_session.return_value = None
    await handler.handle("export", ["deadbeef"], {}, "C1", None, "fred", "U1")
    assert "not found" in _reply_text(handler)


@pytest.mark.asyncio
async def test_export_returns_json(handler):
    session = {
        "id": "aaaabbbbccccdddd",
        "agent_name": "fred",
        "model": "claude-sonnet-4-5",
        "backend": "claude",
        "thread_ts": "1234.5678",
        "label": None,
        "name": "my-session",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_active": None,
        "archived": 0,
        "archive_reason": None,
        "summary": None,
        "ended_cleanly": None,
    }
    handler._db.get_session.return_value = session
    await handler.handle("export", ["aaaabbbbccccdddd"], {}, "C1", None, "fred", "U1")
    text = _reply_text(handler)
    assert "Session export" in text
    # None values should be filtered out
    assert '"label"' not in text
    assert '"id"' in text
    assert '"agent_name"' in text
    # Should be valid JSON inside the code block
    start = text.index("```\n") + 4
    end = text.rindex("\n```")
    parsed = json.loads(text[start:end])
    assert parsed["id"] == "aaaabbbbccccdddd"
    assert parsed["name"] == "my-session"
    # None fields filtered
    assert "label" not in parsed


@pytest.mark.asyncio
async def test_export_calls_get_session_with_id(handler):
    handler._db.get_session.return_value = {
        "id": "xyz",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
    }
    await handler.handle("export", ["xyz"], {}, "C1", None, "fred", "U1")
    handler._db.get_session.assert_called_once_with("xyz")


# ── !import ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_no_args(handler):
    await handler.handle("import", [], {}, "C1", None, "fred", "U1")
    assert "Usage" in _reply_text(handler)


@pytest.mark.asyncio
async def test_import_invalid_json(handler):
    await handler.handle("import", ["not-json"], {}, "C1", None, "fred", "U1")
    assert "Invalid JSON" in _reply_text(handler)


@pytest.mark.asyncio
async def test_import_missing_required_fields(handler):
    data = json.dumps({"id": "abc", "agent_name": "fred"})
    await handler.handle("import", [data], {}, "C1", None, "fred", "U1")
    text = _reply_text(handler)
    assert "Missing required fields" in text
    assert "model" in text
    assert "backend" in text


@pytest.mark.asyncio
async def test_import_success(handler):
    data = {
        "id": "aaaabbbb-1234-5678-abcd-000000000000",
        "agent_name": "fred",
        "model": "claude-sonnet-4-5",
        "backend": "claude",
        "thread_ts": "111.222",
        "label": "imported-label",
        "name": "my-import",
    }
    await handler.handle("import", [json.dumps(data)], {}, "C1", None, "fred", "U1")
    handler._db.create_session.assert_called_once_with(
        id=data["id"],
        agent_name="fred",
        thread_ts="111.222",
        label="imported-label",
        model="claude-sonnet-4-5",
        backend="claude",
    )
    handler._db.update_session_name.assert_called_once_with(data["id"], "my-import")
    text = _reply_text(handler)
    assert "Imported" in text
    assert "fred" in text


@pytest.mark.asyncio
async def test_import_success_without_name(handler):
    """Import without a name field should not call update_session_name."""
    data = {
        "id": "aaaabbbb-0000-0000-0000-000000000000",
        "agent_name": "fred",
        "model": "claude-sonnet-4-5",
        "backend": "claude",
    }
    await handler.handle("import", [json.dumps(data)], {}, "C1", None, "fred", "U1")
    handler._db.create_session.assert_called_once()
    handler._db.update_session_name.assert_not_called()
    assert "Imported" in _reply_text(handler)


@pytest.mark.asyncio
async def test_import_db_error(handler):
    handler._db.create_session.side_effect = Exception("duplicate key")
    data = {
        "id": "aaaabbbb-0000-0000-0000-000000000001",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
    }
    await handler.handle("import", [json.dumps(data)], {}, "C1", None, "fred", "U1")
    assert "Import failed" in _reply_text(handler)


@pytest.mark.asyncio
async def test_import_json_split_across_args(handler):
    """JSON may be passed as multiple space-separated args (shell tokenisation)."""
    raw = '{"id": "aabb", "agent_name": "fred", "model": "m", "backend": "b"}'
    # Simulate how the command parser might tokenise it:
    args = raw.split()
    await handler.handle("import", args, {}, "C1", None, "fred", "U1")
    # Should reconstruct and parse fine
    handler._db.create_session.assert_called_once()


# ── !fork ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fork_no_args(handler):
    await handler.handle("fork", [], {}, "C1", None, "fred", "U1")
    assert "Usage" in _reply_text(handler)


@pytest.mark.asyncio
async def test_fork_session_not_found(handler):
    handler._db.get_session.return_value = None
    await handler.handle("fork", ["deadbeef"], {}, "C1", None, "fred", "U1")
    assert "not found" in _reply_text(handler)


@pytest.mark.asyncio
async def test_fork_creates_new_session(handler):
    source = {
        "id": "source-uuid-1234",
        "agent_name": "fred",
        "model": "claude-sonnet-4-5",
        "backend": "claude",
        "thread_ts": "999.000",
        "name": "original-session",
    }
    handler._db.get_session.return_value = source
    await handler.handle("fork", ["source-uuid-1234"], {}, "C1", None, "fred", "U1")

    # create_session should have been called with a NEW id
    assert handler._db.create_session.called
    call_kwargs = handler._db.create_session.call_args.kwargs
    assert call_kwargs["id"] != "source-uuid-1234"
    assert call_kwargs["agent_name"] == "fred"
    assert call_kwargs["model"] == "claude-sonnet-4-5"
    assert call_kwargs["backend"] == "claude"
    assert "fork" in call_kwargs["label"]


@pytest.mark.asyncio
async def test_fork_sets_fork_name(handler):
    source = {
        "id": "src-0000-1111",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
        "name": "parent",
    }
    handler._db.get_session.return_value = source
    await handler.handle("fork", ["src-0000-1111"], {}, "C1", None, "fred", "U1")

    handler._db.update_session_name.assert_called_once()
    name_arg = handler._db.update_session_name.call_args.args[1]
    assert "fork" in name_arg
    assert "parent" in name_arg


@pytest.mark.asyncio
async def test_fork_does_not_set_current_session(handler):
    """CRITICAL: fork must NOT set agent.current_session_id."""
    source = {
        "id": "src-uuid",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
        "name": "src",
    }
    handler._db.get_session.return_value = source
    agent = handler._agents["fred"]
    agent.current_session_id = "original-session"

    await handler.handle("fork", ["src-uuid"], {}, "C1", None, "fred", "U1")

    # current_session_id must remain unchanged
    assert agent.current_session_id == "original-session"


@pytest.mark.asyncio
async def test_fork_reply_contains_new_id_and_resume_hint(handler):
    source = {
        "id": "src00000000000000",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
        "name": "src-name",
    }
    handler._db.get_session.return_value = source
    await handler.handle("fork", ["src00000000000000"], {}, "C1", None, "fred", "U1")
    text = _reply_text(handler)
    assert "resume" in text.lower() or "!resume" in text


@pytest.mark.asyncio
async def test_fork_unnamed_source_uses_id_prefix(handler):
    """When source has no name, the label/name should use the ID prefix."""
    source = {
        "id": "src00000000000000",
        "agent_name": "fred",
        "model": "m",
        "backend": "b",
        "name": None,
    }
    handler._db.get_session.return_value = source
    await handler.handle("fork", ["src00000000000000"], {}, "C1", None, "fred", "U1")
    assert handler._db.create_session.called
    call_kwargs = handler._db.create_session.call_args.kwargs
    # label should use first 8 chars of source id
    assert "src00000" in call_kwargs["label"]


# ── !help includes new commands ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_includes_export_import_fork(handler):
    await handler.handle("help", [], {}, "C1", None, "fred", "U1")
    text = _reply_text(handler)
    assert "!export" in text
    assert "!import" in text
    assert "!fork" in text
