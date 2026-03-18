"""Tests for cost tracking — backend token extraction and QueryEngine DB logging."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backends.claude import ClaudeBackend
from backends.base import Event
from core.query import QueryEngine, QueryResult


# ── QueryResult cost fields ──────────────────────────────────────────────────

def test_query_result_has_cost_fields():
    result = QueryResult(
        text="hello",
        session_id="sess1",
        success=True,
        cost_usd=0.0042,
        input_tokens=100,
        output_tokens=200,
    )
    assert result.cost_usd == 0.0042
    assert result.input_tokens == 100
    assert result.output_tokens == 200


def test_query_result_cost_fields_default_none():
    result = QueryResult(text="hello", session_id="sess1", success=True)
    assert result.cost_usd is None
    assert result.input_tokens is None
    assert result.output_tokens is None


# ── ClaudeBackend complete event includes token counts ───────────────────────

@pytest.mark.asyncio
async def test_claude_backend_complete_event_has_tokens():
    """complete event raw dict must include input_tokens and output_tokens."""
    from claude_agent_sdk.types import ResultMessage

    backend = ClaudeBackend()
    backend._pending_options = MagicMock()
    backend._pending_options.prompt = ""

    result_msg = MagicMock(spec=ResultMessage)
    result_msg.result = "done"
    result_msg.session_id = "sess-abc"
    result_msg.total_cost_usd = 0.001
    result_msg.duration_ms = 5000
    result_msg.num_turns = 2
    result_msg.input_tokens = 150
    result_msg.output_tokens = 75

    with patch("backends.claude.claude_query", return_value=[result_msg]):
        events = []
        async for event in backend.query("sess-abc", "hello"):
            events.append(event)

    complete_events = [e for e in events if e.type == "complete"]
    assert len(complete_events) == 1
    raw = complete_events[0].raw
    assert raw["input_tokens"] == 150
    assert raw["output_tokens"] == 75
    assert raw["cost_usd"] == 0.001


@pytest.mark.asyncio
async def test_claude_backend_complete_event_tokens_none_when_missing():
    """When ResultMessage has no token attrs, raw values should be None."""
    from claude_agent_sdk.types import ResultMessage

    backend = ClaudeBackend()
    backend._pending_options = MagicMock()
    backend._pending_options.prompt = ""

    result_msg = MagicMock(spec=ResultMessage)
    result_msg.result = "done"
    result_msg.session_id = "sess-xyz"
    # Remove token attrs so getattr returns None
    del result_msg.input_tokens
    del result_msg.output_tokens
    result_msg.total_cost_usd = None
    result_msg.duration_ms = None
    result_msg.num_turns = None

    with patch("backends.claude.claude_query", return_value=[result_msg]):
        events = []
        async for event in backend.query("sess-xyz", "hello"):
            events.append(event)

    complete_events = [e for e in events if e.type == "complete"]
    assert len(complete_events) == 1
    raw = complete_events[0].raw
    assert raw["input_tokens"] is None
    assert raw["output_tokens"] is None


# ── QueryEngine cost capture and DB logging ──────────────────────────────────

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "fred"
    agent.host_id = "host1"
    agent.display_name = "Fred@host1"
    agent.config = MagicMock()
    agent.config.model = "claude-opus-4-5"
    agent.profile = MagicMock()
    agent.profile.allowed_tools = []
    agent.backend = MagicMock()
    agent.backend.name = "claude"
    agent.current_session_id = None
    return agent


@pytest.fixture
def mock_poster():
    poster = AsyncMock()
    poster.post = AsyncMock(return_value={"ts": "111.222"})
    poster.update = AsyncMock()
    return poster


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_cost = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_run_query_captures_cost_from_complete_event(mock_agent):
    """_run_query should populate cost fields on QueryResult from complete event raw."""
    complete_event = Event(
        type="complete",
        content="done",
        detail="sess-111",
        raw={
            "session_id": "sess-111",
            "cost_usd": 0.005,
            "input_tokens": 300,
            "output_tokens": 150,
        },
    )
    text_event = Event(type="text", content="Hello!", raw={})

    async def fake_query(*args, **kwargs):
        yield text_event
        yield complete_event

    mock_agent.backend.query = fake_query

    from core.heartbeat import HeartbeatState
    engine = QueryEngine(
        agent=mock_agent,
        slack_client=AsyncMock(),
        poster=AsyncMock(),
        db=AsyncMock(),
    )
    hb_state = HeartbeatState()
    result = await engine._run_query("hi", None, hb_state)

    assert result.success is True
    assert result.cost_usd == 0.005
    assert result.input_tokens == 300
    assert result.output_tokens == 150
    assert result.session_id == "sess-111"


@pytest.mark.asyncio
async def test_execute_logs_cost_to_db(mock_agent, mock_poster, mock_db):
    """execute() should call db.log_cost when cost data is present."""
    complete_event = Event(
        type="complete",
        content="done",
        detail="sess-222",
        raw={
            "session_id": "sess-222",
            "cost_usd": 0.007,
            "input_tokens": 500,
            "output_tokens": 250,
        },
    )
    text_event = Event(type="text", content="Result text", raw={})

    async def fake_query(*args, **kwargs):
        yield text_event
        yield complete_event

    mock_agent.backend.query = fake_query
    mock_agent.backend.get_session_info = AsyncMock(return_value=MagicMock(
        input_tokens=None, context_limit=None
    ))

    engine = QueryEngine(
        agent=mock_agent,
        slack_client=AsyncMock(),
        poster=mock_poster,
        db=mock_db,
        heartbeat_interval=9999,  # prevent heartbeat from firing
    )

    result = await engine.execute("hi", "C123", thread_ts=None)

    assert result.success is True
    mock_db.log_cost.assert_awaited_once_with(
        agent_name="fred",
        session_id="sess-222",
        input_tokens=500,
        output_tokens=250,
        model="claude-opus-4-5",
    )


@pytest.mark.asyncio
async def test_execute_skips_log_cost_when_no_cost_data(mock_agent, mock_poster, mock_db):
    """execute() should NOT call db.log_cost when cost/token data is absent."""
    complete_event = Event(
        type="complete",
        content="done",
        detail="sess-333",
        raw={"session_id": "sess-333", "cost_usd": None, "input_tokens": None, "output_tokens": None},
    )
    text_event = Event(type="text", content="hi", raw={})

    async def fake_query(*args, **kwargs):
        yield text_event
        yield complete_event

    mock_agent.backend.query = fake_query
    mock_agent.backend.get_session_info = AsyncMock(return_value=MagicMock(
        input_tokens=None, context_limit=None
    ))

    engine = QueryEngine(
        agent=mock_agent,
        slack_client=AsyncMock(),
        poster=mock_poster,
        db=mock_db,
        heartbeat_interval=9999,
    )

    result = await engine.execute("hi", "C123")
    mock_db.log_cost.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_logs_cost_when_only_cost_usd_present(mock_agent, mock_poster, mock_db):
    """log_cost is called even if only cost_usd is present (no token counts)."""
    complete_event = Event(
        type="complete",
        content="done",
        detail="sess-444",
        raw={"session_id": "sess-444", "cost_usd": 0.003, "input_tokens": None, "output_tokens": None},
    )
    text_event = Event(type="text", content="yo", raw={})

    async def fake_query(*args, **kwargs):
        yield text_event
        yield complete_event

    mock_agent.backend.query = fake_query
    mock_agent.backend.get_session_info = AsyncMock(return_value=MagicMock(
        input_tokens=None, context_limit=None
    ))

    engine = QueryEngine(
        agent=mock_agent,
        slack_client=AsyncMock(),
        poster=mock_poster,
        db=mock_db,
        heartbeat_interval=9999,
    )

    result = await engine.execute("hi", "C123")
    mock_db.log_cost.assert_awaited_once()
    call_kwargs = mock_db.log_cost.call_args.kwargs
    assert call_kwargs["input_tokens"] == 0
    assert call_kwargs["output_tokens"] == 0


@pytest.mark.asyncio
async def test_execute_does_not_fail_if_log_cost_raises(mock_agent, mock_poster, mock_db):
    """Cost logging failure must not break execute() — result still returned."""
    mock_db.log_cost = AsyncMock(side_effect=Exception("DB down"))

    complete_event = Event(
        type="complete",
        content="done",
        detail="sess-555",
        raw={"session_id": "sess-555", "cost_usd": 0.001, "input_tokens": 10, "output_tokens": 20},
    )
    text_event = Event(type="text", content="answer", raw={})

    async def fake_query(*args, **kwargs):
        yield text_event
        yield complete_event

    mock_agent.backend.query = fake_query
    mock_agent.backend.get_session_info = AsyncMock(return_value=MagicMock(
        input_tokens=None, context_limit=None
    ))

    engine = QueryEngine(
        agent=mock_agent,
        slack_client=AsyncMock(),
        poster=mock_poster,
        db=mock_db,
        heartbeat_interval=9999,
    )

    result = await engine.execute("hi", "C123")
    assert result.success is True
    assert result.text == "answer"
