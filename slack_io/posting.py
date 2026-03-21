"""Centralized Slack message posting with host-branded colored attachments.

Every outbound message from the hub flows through SlackPoster so that:
- Each agent's messages have a distinct colored sidebar
- The host identity (agent@host) is shown in the attachment footer
- Messages are visually distinguishable across agents and orchestrators
"""

from __future__ import annotations

import colorsys
import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


def _generate_agent_color(agent_name: str, base_color: str) -> str:
    """Generate a distinct color for an agent by shifting hue from base.

    Agents get evenly-spaced hue shifts so colors are visually distinct.
    Saturation and lightness are kept consistent for a cohesive palette.
    """
    h = int(hashlib.sha256(agent_name.encode()).hexdigest()[:8], 16)
    # Use golden ratio to spread hues evenly
    hue = (h * 0.618033988749895) % 1.0
    # Keep saturation/lightness in a pleasant range
    return _hsl_to_hex(hue, 0.55, 0.50)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL (0-1 range) to hex color string."""
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


class SlackPoster:
    """Wraps all outbound Slack messages with host-branded formatting."""

    def __init__(
        self,
        client: AsyncWebClient,
        host_id: str,
        host_color: str = "#4A90E2",
        agent_colors: dict[str, str] | None = None,
    ):
        self._client = client
        self._host_id = host_id
        self._color = host_color
        self._agent_colors = agent_colors or {}
        self._agent_display_names: dict[str, str] = {}

    def set_agent_color(self, agent_name: str, color: str) -> None:
        """Explicitly set a color for an agent."""
        self._agent_colors[agent_name] = color

    def set_agent_display_name(self, agent_name: str, display_name: str) -> None:
        """Register a display name for an agent (used in footers)."""
        self._agent_display_names[agent_name] = display_name

    def get_display_name(self, agent_name: str) -> str:
        """Get the display name for an agent, falling back to capitalized internal name."""
        return self._agent_display_names.get(agent_name, agent_name.capitalize())

    def get_agent_color(self, agent_name: str | None) -> str:
        """Get the sidebar color for an agent (auto-generated if not set)."""
        if not agent_name:
            return self._color
        if agent_name not in self._agent_colors:
            self._agent_colors[agent_name] = _generate_agent_color(
                agent_name, self._color
            )
        return self._agent_colors[agent_name]

    def _build_attachment(
        self,
        text: str,
        agent_name: str | None = None,
        footer_extra: str | None = None,
    ) -> dict:
        """Build a Slack attachment with colored sidebar and host footer."""
        color = self.get_agent_color(agent_name)

        if agent_name:
            display = self.get_display_name(agent_name)
            footer = f"{display} · {self._host_id}"
        else:
            footer = self._host_id

        if footer_extra:
            footer = f"{footer} │ {footer_extra}"

        return {
            "color": color,
            "text": text,
            "fallback": text[:120],  # push notification preview
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
        # Content lives in the attachment only. We omit top-level text to prevent
        # Slack from rendering it twice (above + inside attachment).
        return await self._client.chat_postMessage(
            channel=channel,
            attachments=[attachment],
            text=" ",  # minimal fallback for push notifications
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
            text="",
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
