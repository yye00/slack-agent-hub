import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.query import QueryEngine, QueryResult
from backends.base import Event


@pytest.fixture
def mock_slack_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock()
    return client


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "fred"
    agent.host_id = "host1"
    agent.display_name = "Fred"
    agent.config = MagicMock()
    agent.config.cwd = "/tmp/test"
    agent.profile = MagicMock()
    agent.profile.allowed_tools = ["Read", "Write"]
    agent.backend = MagicMock()
    agent.backend.name = "claude"
    agent.backend.terminal_resume_command.return_value = "claude --resume abc"
    return agent


def test_query_result_creation():
    result = QueryResult(
        text="Hello world",
        session_id="abc123",
        success=True,
    )
    assert result.text == "Hello world"
    assert result.success is True


def test_query_result_error():
    result = QueryResult(
        text="",
        session_id="abc123",
        success=False,
        error="Session expired",
    )
    assert result.success is False
    assert result.error == "Session expired"
