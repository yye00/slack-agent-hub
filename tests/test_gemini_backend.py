"""Tests for Gemini CLI backend adapter."""
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backends.gemini import GeminiBackend
from backends.base import Event, SessionInfo, CommandInfo


# ── Property tests ──

def test_gemini_backend_name():
    backend = GeminiBackend()
    assert backend.name == "gemini"


def test_gemini_capabilities():
    backend = GeminiBackend()
    caps = backend.capabilities()
    assert "session_resume" in caps
    assert "streaming" in caps


def test_gemini_supported_commands():
    backend = GeminiBackend()
    cmds = backend.supported_commands()
    names = [c.name for c in cmds]
    assert "/compact" in names


def test_gemini_terminal_resume_command():
    backend = GeminiBackend()
    cmd = backend.terminal_resume_command("abc123")
    assert "gemini" in cmd
    assert "abc123" in cmd


def test_gemini_terminal_resume_command_none():
    backend = GeminiBackend()
    assert backend.terminal_resume_command("") is None


# ── Session management ──

@pytest.mark.asyncio
async def test_start_session_stores_config():
    backend = GeminiBackend()
    sid = await backend.start_session("/tmp/test", "You are helpful", "gemini-2.5-pro")
    assert sid == ""  # Populated by first query
    assert backend._session_config["cwd"] == "/tmp/test"
    assert backend._session_config["model"] == "gemini-2.5-pro"
    assert backend._session_config["system_prompt"] == "You are helpful"


@pytest.mark.asyncio
async def test_resume_session_stores_id():
    backend = GeminiBackend()
    result = await backend.resume_session("sess-xyz")
    assert result is True
    assert backend._session_config["resume_id"] == "sess-xyz"


@pytest.mark.asyncio
async def test_resume_session_empty_id():
    backend = GeminiBackend()
    result = await backend.resume_session("")
    assert result is False


# ── Query event parsing ──

@pytest.mark.asyncio
async def test_query_parses_text_events():
    """Gemini text events become Event(type='text')."""
    backend = GeminiBackend()
    await backend.start_session("/tmp", "sys", "gemini-2.5-pro")

    fake_lines = [
        json.dumps({"type": "text", "content": "Hello world"}),
        json.dumps({"type": "result", "content": "Hello world", "session_id": "s1", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.gemini.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "Hello"):
            events.append(event)

    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) == 1
    assert text_events[0].content == "Hello world"


@pytest.mark.asyncio
async def test_query_parses_tool_use_events():
    """Gemini tool_call events become Event(type='tool_use')."""
    backend = GeminiBackend()
    await backend.start_session("/tmp", "sys", "gemini-2.5-pro")

    fake_lines = [
        json.dumps({"type": "tool_call", "name": "read_file", "args": {"path": "/tmp/x"}}),
        json.dumps({"type": "result", "content": "done", "session_id": "s1", "usage": {}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.gemini.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "read"):
            events.append(event)

    tool_events = [e for e in events if e.type == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0].content == "read_file"


@pytest.mark.asyncio
async def test_query_parses_complete_event():
    """Gemini result events become Event(type='complete') with session_id and tokens."""
    backend = GeminiBackend()
    await backend.start_session("/tmp", "sys", "gemini-2.5-pro")

    fake_lines = [
        json.dumps({"type": "text", "content": "Hi"}),
        json.dumps({"type": "result", "content": "Hi", "session_id": "sess-42", "usage": {"input_tokens": 100, "output_tokens": 50}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.gemini.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "Hi"):
            events.append(event)

    complete = [e for e in events if e.type == "complete"]
    assert len(complete) == 1
    assert complete[0].raw["session_id"] == "sess-42"
    assert complete[0].raw["input_tokens"] == 100
    assert complete[0].raw["output_tokens"] == 50


@pytest.mark.asyncio
async def test_query_handles_malformed_json():
    """Malformed JSON lines are skipped, not crashed on."""
    backend = GeminiBackend()
    await backend.start_session("/tmp", "sys", "gemini-2.5-pro")

    fake_lines = [
        "not valid json",
        json.dumps({"type": "text", "content": "ok"}),
        json.dumps({"type": "result", "content": "ok", "session_id": "s1", "usage": {}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.gemini.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "test"):
            events.append(event)

    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) == 1


@pytest.mark.asyncio
async def test_query_emits_error_on_process_failure():
    """If subprocess raises, an error event is yielded."""
    backend = GeminiBackend()
    await backend.start_session("/tmp", "sys", "gemini-2.5-pro")

    async def mock_run(*a, **kw):
        raise FileNotFoundError("gemini not found")

    with patch("backends.gemini.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "test"):
            events.append(event)

    assert any(e.type == "error" for e in events)


# ── Cancel ──

@pytest.mark.asyncio
async def test_cancel_is_noop():
    """Cancel doesn't raise."""
    backend = GeminiBackend()
    await backend.cancel("any-id")


# ── Session info ──

@pytest.mark.asyncio
async def test_get_session_info():
    backend = GeminiBackend()
    info = await backend.get_session_info("s1")
    assert info.session_id == "s1"
