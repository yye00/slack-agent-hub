"""Session lifecycle notifications — every state change visible in Slack."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_io.posting import SlackPoster

logger = logging.getLogger(__name__)


@dataclass
class SessionEvent:
    """A session state change event."""
    type: str  # "start", "restart", "death"
    agent_name: str
    agent_display: str
    session_id: str
    channel_id: str
    previous_session_id: str = ""
    reason: str = ""


class LifecycleNotifier:
    """Posts session lifecycle events to Slack."""

    def __init__(self, poster: SlackPoster, ops_channel_id: str):
        self._poster = poster
        self._ops_channel_id = ops_channel_id

    async def notify(self, event: SessionEvent) -> None:
        """Post appropriate notifications for a session event."""
        if event.type == "start":
            await self._notify_start(event)
        elif event.type == "restart":
            await self._notify_restart(event)
        elif event.type == "death":
            await self._notify_death(event)

    async def _notify_start(self, event: SessionEvent) -> None:
        text = (
            f"🟢 *{event.agent_display}* — session started\n"
            f"Session: `{event.session_id[:12]}`"
        )
        await self._post_ops(text, event.agent_name)

    async def _notify_restart(self, event: SessionEvent) -> None:
        ops_text = (
            f"🔄 *{event.agent_display}* — session restarted\n"
            f"New session: `{event.session_id[:12]}` │ "
            f"Previous: `{event.previous_session_id[:12]}`\n"
            f"Reason: {event.reason}"
        )
        await self._post_ops(ops_text, event.agent_name)

        channel_text = (
            f"🔄 Session restarted — previous session "
            f"`{event.previous_session_id[:12]}` ended due to: {event.reason}"
        )
        await self._post_channel(event.channel_id, channel_text, event.agent_name)

    async def _notify_death(self, event: SessionEvent) -> None:
        text = (
            f"💀 *{event.agent_display}* — session died\n"
            f"Session: `{event.session_id[:12]}`\n"
            f"Reason: {event.reason or 'unknown'}"
        )
        await self._post_ops(text, event.agent_name)

    async def _post_ops(self, text: str, agent_name: str) -> None:
        try:
            await self._poster.post(
                channel=self._ops_channel_id,
                text=text,
                agent_name=agent_name,
            )
        except Exception as e:
            logger.error(f"Failed to post lifecycle event to ops: {e}")

    async def _post_channel(self, channel_id: str, text: str, agent_name: str) -> None:
        try:
            await self._poster.post(
                channel=channel_id,
                text=text,
                agent_name=agent_name,
            )
        except Exception as e:
            logger.error(f"Failed to post lifecycle event to channel: {e}")
