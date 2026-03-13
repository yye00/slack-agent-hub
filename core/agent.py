"""Agent class — identity, lifecycle, state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.config import AgentConfig, ProfileConfig

if TYPE_CHECKING:
    from backends.base import Backend
    from storage.db import Database


class Agent:
    """Represents a named agent with its backend, config, and runtime state."""

    def __init__(
        self,
        name: str,
        host_id: str,
        config: AgentConfig,
        profile: ProfileConfig,
        backend: Backend,
        db: Database,
    ):
        self.name = name
        self.host_id = host_id
        self.config = config
        self.profile = profile
        self.backend = backend
        self.db = db

        self.status = "active"
        self.current_session_id: str | None = None
        self.current_thread_ts: str | None = None
        self._active_query_task: asyncio.Task | None = None

    @property
    def display_name(self) -> str:
        return f"{self.name.capitalize()}@{self.host_id}"

    def pause(self):
        self.status = "paused"

    def unpause(self):
        self.status = "active"

    def build_system_prompt(
        self,
        roster_text: str = "",
        pins: list[str] | None = None,
        memory_text: str = "",
    ) -> str:
        """Build the full system prompt with identity, roster, pins, memory."""
        parts = [
            f"You are {self.name.capitalize()}, a {self.backend.name} agent on {self.host_id}.",
            f"Your working directory: {self.config.cwd}",
            f"Your channels: {', '.join(self.config.channels)}",
        ]

        if roster_text:
            parts.append(f"\nAgent roster (current network):\n{roster_text}")

        parts.append(
            '\nTo hand off to another agent: @Name@host: <message>\n'
            'To reference another agent\'s work: "check what Name@host said about X"'
        )

        if pins:
            parts.append("\nPinned context (always active):")
            for pin in pins:
                parts.append(f"  - {pin}")

        if memory_text:
            parts.append(f"\n<agent_memory>\n{memory_text}\n</agent_memory>")

        return "\n".join(parts)
