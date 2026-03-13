import pytest
from unittest.mock import AsyncMock, MagicMock

from core.command_handler import CommandHandler


@pytest.fixture
def handler():
    agents = {
        "fred": MagicMock(
            name="fred",
            display_name="Fred@host1",
            backend=MagicMock(name="claude"),
            config=MagicMock(model="claude-sonnet-4-5", profile="dev", cwd="/tmp/test"),
            status="active",
            current_session_id="abc123",
            _active_query_task=None,
        ),
    }
    db = AsyncMock()
    slack_client = AsyncMock()
    return CommandHandler(agents=agents, db=db, slack_client=slack_client)


@pytest.mark.asyncio
async def test_handle_agents(handler):
    await handler.handle("agents", [], {}, "C123", None, "fred", "U_USER")
    handler._slack.chat_postMessage.assert_called_once()
    call_text = handler._slack.chat_postMessage.call_args.kwargs["text"]
    assert "Fred@host1" in call_text


@pytest.mark.asyncio
async def test_handle_help(handler):
    await handler.handle("help", [], {}, "C123", None, "fred", "U_USER")
    handler._slack.chat_postMessage.assert_called_once()
    call_text = handler._slack.chat_postMessage.call_args.kwargs["text"]
    assert "!agents" in call_text


@pytest.mark.asyncio
async def test_handle_unknown_command(handler):
    await handler.handle("nonexistent", [], {}, "C123", None, "fred", "U_USER")
    call_text = handler._slack.chat_postMessage.call_args.kwargs["text"]
    assert "Unknown command" in call_text
