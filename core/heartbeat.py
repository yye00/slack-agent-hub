"""Heartbeat state tracking and tip rotation."""

from __future__ import annotations

import time
from collections import OrderedDict


class HeartbeatState:
    """Tracks progress of an in-flight query for heartbeat display."""

    def __init__(self):
        self.tool_count: int = 0
        self.last_tool: str = ""
        self.recent_tools: list[str] = []  # Ring buffer, max 5
        self._tool_categories: dict[str, int] = {}
        self._last_tool_time: float | None = None
        self.start_time: float = time.monotonic()

    def record_tool(self, tool_name: str, detail: str = ""):
        """Record a tool call."""
        self.tool_count += 1
        detail_short = detail[:50] if detail else ""
        self.last_tool = f"{tool_name} {detail_short}".strip()

        compressed = f"{tool_name}({detail_short})" if detail_short else tool_name
        self.recent_tools.append(compressed)
        if len(self.recent_tools) > 5:
            self.recent_tools.pop(0)

        category = tool_name.split("(")[0]
        self._tool_categories[category] = self._tool_categories.get(category, 0) + 1
        self._last_tool_time = time.monotonic()

    def tool_counts_by_category(self) -> dict[str, int]:
        return dict(self._tool_categories)

    def elapsed_secs(self) -> int:
        return int(time.monotonic() - self.start_time)

    def is_stalled(self, threshold_secs: int = 300) -> bool:
        """Check if no tool activity for threshold_secs."""
        if self._last_tool_time is None:
            return False  # No tools yet — just started
        return (time.monotonic() - self._last_tool_time) > threshold_secs

    def stall_secs(self) -> int:
        if self._last_tool_time is None:
            return 0
        return int(time.monotonic() - self._last_tool_time)


class TipRotator:
    """Cycles through tips without repeating until all shown."""

    def __init__(self, tips: list[str], enabled: bool = True):
        self._tips = tips
        self._enabled = enabled
        self._index = 0

    def next(self) -> str | None:
        if not self._enabled or not self._tips:
            return None
        tip = self._tips[self._index % len(self._tips)]
        self._index += 1
        return tip
