"""Tests for Codex CLI backend adapter."""
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock

from backends.codex import CodexBackend
from backends.base import Event, SessionInfo, CommandInfo


# ── Property tests ──

def test_codex_backend_name():
    backend = CodexBackend()
    assert backend.name == "codex"


def test_codex_capabilities():
    backend = CodexBackend()
    caps = backend.capabilities()
    assert "session_resume" in caps
    assert "streaming" in caps


def test_codex_supported_commands():
    backend = CodexBackend()
    cmds = backend.supported_commands()
    assert isinstance(cmds, list)


def test_codex_terminal_resume_command():
    backend = CodexBackend()
    cmd = backend.terminal_resume_command("abc123")
    assert cmd == "codex exec resume abc123"


def test_codex_terminal_resume_command_none():
    backend = CodexBackend()
    assert backend.terminal_resume_command("") is None


# ── Session management ──

@pytest.mark.asyncio
async def test_start_session_stores_config():
    backend = CodexBackend()
    sid = await backend.start_session("/tmp/test", "You are helpful", "o3")
    assert sid == ""
    assert backend._session_config["cwd"] == "/tmp/test"
    assert backend._session_config["model"] == "o3"


@pytest.mark.asyncio
async def test_resume_session_stores_id():
    backend = CodexBackend()
    result = await backend.resume_session("sess-xyz")
    assert result is True
    assert backend._session_config["resume_id"] == "sess-xyz"


@pytest.mark.asyncio
async def test_resume_session_empty_id():
    backend = CodexBackend()
    result = await backend.resume_session("")
    assert result is False


# ── Query event parsing ──

@pytest.mark.asyncio
async def test_query_parses_text_events():
    """Codex item.completed agent_message events become Event(type='text')."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    fake_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Hello"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "Hello"):
            events.append(event)

    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) == 1
    assert text_events[0].content == "Hello"


@pytest.mark.asyncio
async def test_query_parses_tool_use_events():
    """Codex item.completed function_call events become Event(type='tool_use')."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    fake_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "function_call", "name": "shell", "arguments": '{"cmd":"ls"}'}}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "list files"):
            events.append(event)

    tool_events = [e for e in events if e.type == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0].content == "shell"


@pytest.mark.asyncio
async def test_query_parses_complete_event():
    """Codex turn.completed events become Event(type='complete') with session_id and tokens."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    fake_lines = [
        json.dumps({"type": "thread.started", "thread_id": "sess-99"}),
        json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Done"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 100}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "Do it"):
            events.append(event)

    complete = [e for e in events if e.type == "complete"]
    assert len(complete) == 1
    assert complete[0].raw["session_id"] == "sess-99"
    assert complete[0].raw["input_tokens"] == 200


@pytest.mark.asyncio
async def test_query_handles_malformed_json():
    """Malformed JSON lines are skipped."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    fake_lines = [
        "garbage",
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "ok"}}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "test"):
            events.append(event)

    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) == 1


@pytest.mark.asyncio
async def test_query_emits_error_on_process_failure():
    """If subprocess raises, an error event is yielded."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    async def mock_run(*a, **kw):
        raise FileNotFoundError("codex not found")

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "test"):
            events.append(event)

    assert any(e.type == "error" for e in events)


@pytest.mark.asyncio
async def test_query_handles_turn_failed():
    """Codex turn.failed events become error events."""
    backend = CodexBackend()
    await backend.start_session("/tmp", "sys", "o3")

    fake_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.failed", "error": {"message": "model not supported"}}),
    ]

    async def mock_run(*a, **kw):
        for line in fake_lines:
            yield line

    with patch("backends.codex.run_cli_query", side_effect=mock_run):
        events = []
        async for event in backend.query("", "test"):
            events.append(event)

    assert any(e.type == "error" for e in events)


def test_build_command_skips_default_model():
    """When model is 'codex', don't pass -m flag."""
    backend = CodexBackend()
    backend._session_config = {"model": "codex", "cwd": "/tmp"}
    cmd = backend._build_command("hello")
    assert "-m" not in cmd


def test_build_command_passes_custom_model():
    """When model is specific, pass -m flag."""
    backend = CodexBackend()
    backend._session_config = {"model": "o3", "cwd": "/tmp"}
    cmd = backend._build_command("hello")
    assert "-m" in cmd
    idx = cmd.index("-m")
    assert cmd[idx + 1] == "o3"


# ── Cancel / info ──

@pytest.mark.asyncio
async def test_cancel_is_noop():
    backend = CodexBackend()
    await backend.cancel("any-id")


@pytest.mark.asyncio
async def test_get_session_info():
    backend = CodexBackend()
    info = await backend.get_session_info("s1")
    assert info.session_id == "s1"
