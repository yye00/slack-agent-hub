"""Channel history fetch and summarization."""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def fetch_transcript(
    client: AsyncWebClient,
    channel_id: str,
    days: int = 7,
    keyword: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch channel messages from the last N days."""
    oldest = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    messages = []
    cursor = None

    while True:
        try:
            kwargs = {
                "channel": channel_id,
                "oldest": str(oldest),
                "limit": 100,
            }
            if cursor:
                kwargs["cursor"] = cursor

            resp = await client.conversations_history(**kwargs)
            msgs = resp.get("messages", [])
            messages.extend(msgs)

            if len(messages) >= limit:
                messages = messages[:limit]
                break

            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        except Exception as e:
            if "rate_limited" in str(e).lower():
                await asyncio.sleep(3)
                continue
            logger.error(f"Failed to fetch transcript: {e}")
            break

    messages.reverse()  # oldest first

    if keyword:
        keyword_lower = keyword.lower()
        messages = [m for m in messages if keyword_lower in m.get("text", "").lower()]

    return messages


def summarize_for_onboarding(messages: list[dict], max_chars: int = 8000) -> str:
    """Format messages as a transcript for onboarding."""
    lines = []
    for msg in messages:
        text = msg.get("text", "")
        user = msg.get("user", "unknown")
        lines.append(f"<@{user}>: {text}")

    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n[truncated]"

    return transcript
