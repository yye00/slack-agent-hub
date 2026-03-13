"""Slack permalink expansion — fetch linked messages and inject as context."""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

PERMALINK_RE = re.compile(
    r"https://\S+\.slack\.com/archives/(\w+)/p(\d{10})(\d{6})"
)


async def expand_permalinks(
    client: AsyncWebClient, text: str
) -> str:
    """Find Slack permalinks in text, fetch the messages, prepend as context."""
    matches = list(PERMALINK_RE.finditer(text))
    if not matches:
        return text

    context_parts = []
    for m in matches:
        channel_id = m.group(1)
        ts = f"{m.group(2)}.{m.group(3)}"

        try:
            resp = await client.conversations_history(
                channel=channel_id, latest=ts, oldest=ts, inclusive=True, limit=1
            )
            msgs = resp.get("messages", [])
            if not msgs:
                continue

            msg = msgs[0]
            msg_text = msg.get("text", "")
            user = msg.get("user", "unknown")

            # Fetch thread replies if any
            thread_ts = msg.get("thread_ts")
            replies_text = ""
            if thread_ts:
                try:
                    thread_resp = await client.conversations_replies(
                        channel=channel_id, ts=thread_ts, limit=20
                    )
                    replies = thread_resp.get("messages", [])[1:]  # skip parent
                    if replies:
                        reply_lines = [
                            f"  <@{r.get('user', '?')}>: {r.get('text', '')}"
                            for r in replies
                        ]
                        replies_text = "\n--- Thread Replies ---\n" + "\n".join(reply_lines)
                except Exception:
                    pass

            context_parts.append(
                f'<referenced_slack_message channel_id="{channel_id}" user="<@{user}>" ts="{ts}">\n'
                f"{msg_text}{replies_text}\n"
                f"</referenced_slack_message>"
            )
        except Exception as e:
            logger.debug(f"Failed to expand permalink: {e}")

    if context_parts:
        return "\n".join(context_parts) + "\n\n" + text
    return text
