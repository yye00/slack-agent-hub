"""Tests for new commands: !restart, !roster, !history, !context, !search, !reload, and rewritten !help."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.command_handler import CommandHandler


@pytest.fixture
def agents():
    agent_fred = MagicMock()
    agent_fred.name = "fred"
    agent_fred.display_name = "Fred@host1"
    agent_fred.backend = MagicMock()
    agent_fred.backend.name = "claude"
    agent_fred.config = MagicMock()
    agent_fred.config.model = "claude-sonnet-4-5"
    agent_fred.config.profile = "dev"
    agent_fred.config.cwd = "/tmp/test"
    agent_fred.config.channels = ["#general", "#dev"]
    agent_fred.status = "active"
    agent_fred.current_session_id = "abc123def456"
    agent_fred.host_id = "host1"
    agent_fred._active_query_task = None

    agent_barb = MagicMock()
    agent_barb.name = "barb"
    agent_barb.display_name = "Barb@host1"
    agent_barb.backend = MagicMock()
    agent_barb.backend.name = "claude"
    agent_barb.config = MagicMock()
    agent_barb.config.model = "claude-opus-4-5"
    agent_barb.config.profile = "ops"
    agent_barb.config.cwd = "/tmp/barb"
    agent_barb.config.channels = ["#ops"]
    agent_barb.status = "paused"
    agent_barb.current_session_id = None
    agent_barb.host_id = "host1"
    agent_barb._active_query_task = None

    return {"fred": agent_fred, "barb": agent_barb}


@pytest.fixture
def handler(agents):
    db = AsyncMock()
    slack_client = AsyncMock()
    poster = AsyncMock()
    poster.post = AsyncMock()
    return CommandHandler(agents=agents, db=db, slack_client=slack_client, poster=poster)


def get_reply_text(handler):
    """Helper to extract text from last poster.post call."""
    return handler._poster.post.call_args.kwargs["text"]


# ---------------------------------------------------------------------------
# !restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restart_named_agent(handler, agents):
    """!restart <name> clears the session and reports previous session ID."""
    await handler.handle("restart", ["fred"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "fred" in text.lower() or "Fred" in text
    # Previous session should be mentioned
    assert "abc123" in text
    # Session should now be None
    assert agents["fred"].current_session_id is None


@pytest.mark.asyncio
async def test_restart_no_previous_session(handler, agents):
    """!restart on an agent without a session still works."""
    await handler.handle("restart", ["barb"], {}, "C123", None, "barb", "U1")
    text = get_reply_text(handler)
    assert "Barb" in text
    # No previous session — no session ID in message
    assert "abc123" not in text


@pytest.mark.asyncio
async def test_restart_unknown_agent(handler):
    """!restart <unknown> returns an error."""
    await handler.handle("restart", ["nobody"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "Unknown agent" in text or "unknown" in text.lower()


@pytest.mark.asyncio
async def test_restart_defaults_to_target_agent(handler, agents):
    """!restart with no args uses target_agent."""
    await handler.handle("restart", [], {}, "C123", None, "fred", "U1")
    assert agents["fred"].current_session_id is None


# ---------------------------------------------------------------------------
# !roster
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roster_lists_all_agents(handler):
    """!roster shows every agent."""
    await handler.handle("roster", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "Fred@host1" in text
    assert "Barb@host1" in text


@pytest.mark.asyncio
async def test_roster_includes_channels(handler):
    """!roster includes channel info."""
    await handler.handle("roster", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "#general" in text or "general" in text


@pytest.mark.asyncio
async def test_roster_shows_status_icons(handler):
    """!roster uses status icons (green for active, yellow for paused)."""
    await handler.handle("roster", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    # Active agent gets green, paused gets yellow
    assert "🟢" in text
    assert "🟡" in text


# ---------------------------------------------------------------------------
# !history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_default_limit(handler):
    """!history fetches 10 messages by default."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": f"msg{i}"} for i in range(10)]}
    )
    await handler.handle("history", [], {}, "C123", None, "fred", "U1")
    handler._slack.conversations_history.assert_called_once_with(channel="C123", limit=10)
    text = get_reply_text(handler)
    assert "10" in text


@pytest.mark.asyncio
async def test_history_custom_limit(handler):
    """!history N fetches N messages."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "hi"} for _ in range(5)]}
    )
    await handler.handle("history", ["5"], {}, "C123", None, "fred", "U1")
    handler._slack.conversations_history.assert_called_once_with(channel="C123", limit=5)


@pytest.mark.asyncio
async def test_history_slack_error(handler):
    """!history handles Slack API errors gracefully."""
    handler._slack.conversations_history = AsyncMock(side_effect=Exception("API error"))
    await handler.handle("history", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "Failed" in text or "failed" in text


# ---------------------------------------------------------------------------
# !context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_default_limit(handler):
    """!context fetches 20 messages by default."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "hi"} for _ in range(20)]}
    )
    await handler.handle("context", [], {}, "C123", None, "fred", "U1")
    handler._slack.conversations_history.assert_called_once_with(channel="C123", limit=20)


@pytest.mark.asyncio
async def test_context_labels_as_context(handler):
    """!context output is labeled as context."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "hello"}]}
    )
    await handler.handle("context", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "context" in text.lower()


@pytest.mark.asyncio
async def test_context_custom_limit(handler):
    """!context N fetches N messages."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": []}
    )
    await handler.handle("context", ["7"], {}, "C123", None, "fred", "U1")
    handler._slack.conversations_history.assert_called_once_with(channel="C123", limit=7)


@pytest.mark.asyncio
async def test_context_slack_error(handler):
    """!context handles Slack API errors gracefully."""
    handler._slack.conversations_history = AsyncMock(side_effect=Exception("boom"))
    await handler.handle("context", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "Failed" in text or "failed" in text


# ---------------------------------------------------------------------------
# !search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_finds_keyword(handler):
    """!search <keyword> returns matching messages."""
    handler._slack.conversations_history = AsyncMock(
        return_value={
            "messages": [
                {"user": "U1", "text": "hello world"},
                {"user": "U2", "text": "goodbye world"},
                {"user": "U3", "text": "nothing here"},
            ]
        }
    )
    await handler.handle("search", ["world"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "2" in text  # 2 matches
    assert "world" in text


@pytest.mark.asyncio
async def test_search_case_insensitive(handler):
    """!search is case-insensitive."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "Hello WORLD"}]}
    )
    await handler.handle("search", ["hello"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "1" in text


@pytest.mark.asyncio
async def test_search_no_matches(handler):
    """!search reports when no matches are found."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "something else"}]}
    )
    await handler.handle("search", ["xyzzy"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "No matches" in text or "not found" in text.lower()


@pytest.mark.asyncio
async def test_search_no_args(handler):
    """!search without a keyword shows usage hint."""
    await handler.handle("search", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "Usage" in text or "usage" in text


@pytest.mark.asyncio
async def test_search_multi_word_keyword(handler):
    """!search with multiple words joins them."""
    handler._slack.conversations_history = AsyncMock(
        return_value={"messages": [{"user": "U1", "text": "deploy to prod now"}]}
    )
    await handler.handle("search", ["deploy", "to", "prod"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "1" in text


@pytest.mark.asyncio
async def test_search_slack_error(handler):
    """!search handles Slack API errors gracefully."""
    handler._slack.conversations_history = AsyncMock(side_effect=Exception("API down"))
    await handler.handle("search", ["test"], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "failed" in text.lower() or "Search failed" in text


# ---------------------------------------------------------------------------
# !reload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reload_success(handler, tmp_path):
    """!reload loads config and reports counts."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "host_id: testhost\n"
        "host_name: testhost\n"
        "ops_channel: C_OPS\n"
        "registry_channel: C_REG\n"
        "backends:\n"
        "  claude:\n"
        "    api_key: test\n"
        "profiles:\n"
        "  dev:\n"
        "    allowed_tools: []\n"
        "    permission_mode: default\n"
        "agents:\n"
        "  fred:\n"
        "    backend: claude\n"
        "    model: claude-sonnet-4-5\n"
        "    channels: ['#dev']\n"
        "    cwd: /tmp\n"
        "    profile: dev\n"
        "heartbeat:\n"
        "  interval_secs: 15\n"
        "  tips: true\n"
        "  stall_warn_mins: 5\n"
        "monitors:\n"
        "  default_poll_secs: 30\n"
        "transcript:\n"
        "  lookback_days: 7\n"
        "  onboarding: true\n"
        "permissions: {}\n"
    )
    with patch.dict("os.environ", {"CONFIG_PATH": str(config_file)}):
        await handler.handle("reload", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "reloaded" in text.lower() or "Reloaded" in text
    assert "1" in text  # 1 agent
    assert "1" in text  # 1 profile


@pytest.mark.asyncio
async def test_reload_missing_file(handler, tmp_path):
    """!reload with a missing config file reports an error."""
    with patch.dict("os.environ", {"CONFIG_PATH": str(tmp_path / "missing.yaml")}):
        await handler.handle("reload", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "failed" in text.lower() or "❌" in text


# ---------------------------------------------------------------------------
# !help (rewritten)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_contains_all_sections(handler):
    """Rewritten !help has organized sections."""
    await handler.handle("help", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    # Agent section
    assert "!agents" in text
    assert "!status" in text
    assert "!restart" in text
    # Session section
    assert "!new" in text
    assert "!sessions" in text
    assert "!resume" in text
    # Diagnostics
    assert "!health" in text
    assert "!diag" in text
    assert "!logs" in text
    # Memory / context
    assert "!pin" in text
    assert "!history" in text
    assert "!context" in text
    assert "!search" in text
    # Admin
    assert "!cost" in text
    assert "!roster" in text
    assert "!reload" in text


@pytest.mark.asyncio
async def test_help_mentions_model_flag(handler):
    """!help documents the --model flag."""
    await handler.handle("help", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "--model" in text


@pytest.mark.asyncio
async def test_help_mentions_profiles(handler):
    """!help explains profiles."""
    await handler.handle("help", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert "profile" in text.lower()


@pytest.mark.asyncio
async def test_help_mentions_cli_passthrough(handler):
    """!help mentions > /command CLI passthrough."""
    await handler.handle("help", [], {}, "C123", None, "fred", "U1")
    text = get_reply_text(handler)
    assert ">" in text  # CLI passthrough prefix
