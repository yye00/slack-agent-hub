"""Tests for session lifecycle notifications (ISSUES.md #5)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from core.lifecycle import LifecycleNotifier, SessionEvent


@pytest.fixture
def poster():
    p = AsyncMock()
    p.post = AsyncMock(return_value={"ts": "1234.5678"})
    return p


@pytest.fixture
def notifier(poster):
    return LifecycleNotifier(
        poster=poster,
        ops_channel_id="C_OPS",
    )


@pytest.mark.asyncio
async def test_session_start_posts_to_ops_channel(notifier, poster):
    """When a new session starts, a notification is posted to the ops channel."""
    await notifier.notify(SessionEvent(
        type="start",
        agent_name="fred",
        agent_display="Fred@host1",
        session_id="abc-123",
        channel_id="C_SPE",
    ))
    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args[1]
    assert call_kwargs["channel"] == "C_OPS"
    assert "fred" in call_kwargs["text"].lower() or "Fred" in call_kwargs["text"]
    assert "abc-123" in call_kwargs["text"] or "abc" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_session_restart_posts_to_both_channels(notifier, poster):
    """When a session restarts, both ops and agent channel get notifications."""
    await notifier.notify(SessionEvent(
        type="restart",
        agent_name="fred",
        agent_display="Fred@host1",
        session_id="new-456",
        channel_id="C_SPE",
        previous_session_id="old-123",
        reason="crash",
    ))
    assert poster.post.call_count == 2
    channels = [c[1]["channel"] for c in poster.post.call_args_list]
    assert "C_OPS" in channels
    assert "C_SPE" in channels


@pytest.mark.asyncio
async def test_session_death_posts_to_ops_channel(notifier, poster):
    """When a session dies unexpectedly, ops channel is notified with the reason."""
    await notifier.notify(SessionEvent(
        type="death",
        agent_name="fred",
        agent_display="Fred@host1",
        session_id="abc-123",
        channel_id="C_SPE",
        reason="backend process exited with code 1",
    ))
    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args[1]
    assert call_kwargs["channel"] == "C_OPS"
    assert "died" in call_kwargs["text"].lower() or "death" in call_kwargs["text"].lower() or "exited" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_restart_notification_includes_previous_session_id(notifier, poster):
    """Restart notification includes the ID of the previous session."""
    await notifier.notify(SessionEvent(
        type="restart",
        agent_name="fred",
        agent_display="Fred@host1",
        session_id="new-456",
        channel_id="C_SPE",
        previous_session_id="old-123",
        reason="context limit",
    ))
    agent_channel_calls = [
        c for c in poster.post.call_args_list
        if c[1]["channel"] == "C_SPE"
    ]
    assert len(agent_channel_calls) == 1
    text = agent_channel_calls[0][1]["text"]
    assert "old-123" in text


@pytest.mark.asyncio
async def test_restart_notification_includes_reason(notifier, poster):
    """Restart notification includes the reason for the restart."""
    await notifier.notify(SessionEvent(
        type="restart",
        agent_name="fred",
        agent_display="Fred@host1",
        session_id="new-456",
        channel_id="C_SPE",
        previous_session_id="old-123",
        reason="context limit reached",
    ))
    agent_channel_calls = [
        c for c in poster.post.call_args_list
        if c[1]["channel"] == "C_SPE"
    ]
    text = agent_channel_calls[0][1]["text"]
    assert "context limit" in text.lower()
