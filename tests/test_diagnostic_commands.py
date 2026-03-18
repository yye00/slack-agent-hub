"""Tests for diagnostic commands (ISSUES.md #10)."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_agent(name="agent1", host_id="testhost", status="active",
               session_id=None, query_task=None, backend_name="claude",
               model="claude-opus-4-5", cwd="/tmp/work", profile="default",
               permission_mode="default", stderr_lines="line1\nline2\nline3"):
    """Build a minimal mock Agent."""
    agent = MagicMock()
    agent.name = name
    agent.host_id = host_id
    agent.status = status
    agent.current_session_id = session_id
    agent._active_query_task = query_task
    agent.display_name = f"{name.capitalize()}@{host_id}"

    agent.backend = MagicMock()
    agent.backend.name = backend_name
    agent.backend.last_stderr = stderr_lines

    agent.config = MagicMock()
    agent.config.model = model
    agent.config.cwd = cwd
    agent.config.profile = profile

    agent.profile = MagicMock()
    agent.profile.permission_mode = permission_mode

    return agent


def make_handler(agents):
    """Build a CommandHandler with mocked poster."""
    from core.command_handler import CommandHandler

    poster = MagicMock()
    poster.post = AsyncMock()

    handler = CommandHandler(
        agents=agents,
        db=MagicMock(),
        slack_client=MagicMock(),
        poster=poster,
    )
    return handler, poster


@pytest.mark.asyncio
async def test_health_command_returns_summary():
    """!health returns hub health summary with agents, backends, connections."""
    agent = make_agent("agent1", host_id="myhost", session_id="sess-abc-123")
    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="health",
        args=[],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    assert "Hub health" in text
    assert "myhost" in text
    assert "Agents:" in text
    assert "Queries in flight:" in text


@pytest.mark.asyncio
async def test_logs_command_returns_recent_lines():
    """!logs agent N returns the last N log lines for the specified agent."""
    stderr = "\n".join(f"log line {i}" for i in range(50))
    agent = make_agent("agent1", stderr_lines=stderr)
    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="logs",
        args=["agent1", "5"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    # Should include the last 5 lines
    assert "log line 49" in text
    assert "log line 45" in text
    # Should NOT include line 44 (outside last 5)
    assert "log line 44" not in text


@pytest.mark.asyncio
async def test_logs_command_defaults_to_20():
    """!logs agent without N defaults to 20 lines."""
    stderr = "\n".join(f"log line {i}" for i in range(50))
    agent = make_agent("agent1", stderr_lines=stderr)
    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="logs",
        args=["agent1"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    # Default 20 lines: lines 30..49
    assert "log line 49" in text
    assert "log line 30" in text
    # line 29 is outside default 20
    assert "log line 29" not in text
    assert "last 20 lines" in text


@pytest.mark.asyncio
async def test_diag_command_shows_session_state():
    """!diag agent shows session state, pending queries, memory usage, backend status."""
    running_task = MagicMock()
    running_task.done.return_value = False

    agent = make_agent(
        "agent1",
        session_id="sess-xyz-789",
        query_task=running_task,
        model="claude-opus-4-5",
        cwd="/home/user/project",
        profile="developer",
        permission_mode="bypassPermissions",
        stderr_lines="some stderr output",
    )
    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="diag",
        args=["agent1"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    assert "Diagnostics" in text
    assert "sess-xyz-789" in text
    assert "Query active: yes" in text
    assert "claude-opus-4-5" in text
    assert "/home/user/project" in text
    assert "developer" in text
    assert "bypassPermissions" in text
    assert "some stderr output" in text


@pytest.mark.asyncio
async def test_test_command_sends_trivial_query():
    """!test agent sends a trivial query and reports whether the backend responds."""
    from backends.base import Event

    async def mock_query(session_id, prompt, allowed_tools=None):
        yield Event(type="text", content="ok", raw={})
        yield Event(type="complete", content="", raw={})

    agent = make_agent("agent1", session_id="sess-active-123")
    agent.backend.query = mock_query

    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="test",
        args=["agent1"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    assert poster.post.call_count == 2  # "Testing…" + result
    result_text = poster.post.call_args_list[-1].kwargs["text"]
    assert "responded" in result_text
    assert "ok" in result_text


@pytest.mark.asyncio
async def test_test_command_reports_failure():
    """!test agent reports failure clearly when backend is unresponsive."""
    async def failing_query(session_id, prompt, allowed_tools=None):
        raise ConnectionError("backend is unreachable")
        # Make it an async generator
        yield  # pragma: no cover

    agent = make_agent("agent1", session_id="sess-active-123")
    agent.backend.query = failing_query

    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="test",
        args=["agent1"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    result_text = poster.post.call_args_list[-1].kwargs["text"]
    assert "failed" in result_text
    assert "backend is unreachable" in result_text


@pytest.mark.asyncio
async def test_test_command_refuses_without_session():
    """!test refuses to run if the agent has no active session."""
    agent = make_agent("agent1", session_id=None)
    handler, poster = make_handler({"agent1": agent})

    await handler.handle(
        command="test",
        args=["agent1"],
        options={},
        channel_id="C1",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    assert "no active session" in text
