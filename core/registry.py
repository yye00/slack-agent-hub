"""Federation registry — agent discovery via Slack channel."""

from __future__ import annotations

import re
from datetime import datetime, timezone


def format_registry_message(host_id: str, agents_info: list[dict]) -> str:
    """Format a registration message for #agent-registry."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"📡 {host_id} online │ last seen: {now}"]
    for a in agents_info:
        channels = ", ".join(a["channels"]) if isinstance(a["channels"], list) else a["channels"]
        lines.append(
            f"{a['name'].capitalize()} ({a['backend']} {a['model']}) │ {channels} │ {a['status']}"
        )
    return "\n".join(lines)


_HEADER_RE = re.compile(r"📡\s+(\S+)\s+(\w+)\s+│")
_AGENT_RE = re.compile(
    r"^(\w+)\s+\((\w+)\s+([^)]+)\)\s+│\s+([^│]+)│\s+(\w+)",
    re.MULTILINE,
)


def parse_registry_messages(messages: list[dict]) -> list[dict]:
    """Parse registry messages into a roster."""
    roster = []
    for msg in messages:
        text = msg.get("text", "")
        header = _HEADER_RE.search(text)
        if not header:
            continue
        host_id = header.group(1)

        for m in _AGENT_RE.finditer(text):
            roster.append({
                "name": m.group(1),
                "host": host_id,
                "backend": m.group(2),
                "model": m.group(3).strip(),
                "channels": m.group(4).strip().rstrip("│").strip(),
                "status": m.group(5),
            })
    return roster


def build_roster_text(
    roster: list[dict], self_name: str, self_host: str
) -> str:
    """Build roster text for system prompt injection."""
    lines = []
    for a in roster:
        is_self = a["name"].lower() == self_name.lower() and a["host"] == self_host
        suffix = " (you)" if is_self else ""
        lines.append(
            f"  {a['name']}@{a['host']}{suffix} — {a['backend']} {a['model']} │ {a['channels']}"
        )
    return "\n".join(lines)
