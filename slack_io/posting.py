"""Centralized Slack message posting with host-branded colored attachments.

Every outbound message from the hub flows through SlackPoster so that:
- Each host's messages have a distinct colored sidebar
- The host identity (agent@host) is shown in the attachment footer
- Messages are visually distinguishable across orchestrators
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackPoster:
    """Wraps all outbound Slack messages with host-branded formatting."""

    def __init__(
        self,
        client: AsyncWebClient,
        host_id: str,
        host_color: str = "#4A90E2",
    ):
        self._client = client
        self._host_id = host_id
        self._color = host_color

    def _build_attachment(
        self,
        text: str,
        agent_name: str | None = None,
        footer_extra: str | None = None,
    ) -> dict:
        """Build a Slack attachment with colored sidebar and host footer."""
        if agent_name:
            footer = f"{agent_name}@{self._host_id}"
        else:
            footer = self._host_id

        if footer_extra:
            footer = f"{footer} │ {footer_extra}"

        return {
            "color": self._color,
            "text": text,
            "footer": footer,
            "mrkdwn_in": ["text"],
        }

    async def post(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        agent_name: str | None = None,
        footer_extra: str | None = None,
    ) -> dict:
        """Post a new branded message. Returns the API response."""
        attachment = self._build_attachment(text, agent_name, footer_extra)
        return await self._client.chat_postMessage(
            channel=channel,
            attachments=[attachment],
            text=text,  # fallback for notifications
            thread_ts=thread_ts,
        )

    async def update(
        self,
        channel: str,
        ts: str,
        text: str,
        agent_name: str | None = None,
        footer_extra: str | None = None,
    ) -> dict:
        """Update an existing message with branded formatting."""
        attachment = self._build_attachment(text, agent_name, footer_extra)
        return await self._client.chat_update(
            channel=channel,
            ts=ts,
            attachments=[attachment],
            text=text,  # fallback
        )

    async def post_plain(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict:
        """Post without branding (for heartbeat placeholder, etc.)."""
        return await self._client.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )
