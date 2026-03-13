"""Cross-agent handoff detection and processing."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HANDOFF_PATTERN = re.compile(r"^@(\w+)@([\w-]+):\s*(.*)", re.MULTILINE)


@dataclass
class HandoffRequest:
    target_agent: str
    target_host: str
    content: str


def detect_handoff_in_response(response_text: str) -> HandoffRequest | None:
    """Detect a handoff pattern in an agent's response."""
    lines = response_text.split("\n")
    for i, line in enumerate(lines):
        m = _HANDOFF_PATTERN.match(line)
        if m:
            # Capture everything from the handoff line onward
            first_line_content = m.group(3).strip()
            remaining_lines = lines[i + 1:]
            remaining = "\n".join(remaining_lines).strip()
            content = first_line_content
            if remaining:
                content = content + "\n" + remaining if content else remaining

            return HandoffRequest(
                target_agent=m.group(1).lower(),
                target_host=m.group(2),
                content=content,
            )
    return None
