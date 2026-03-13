"""Backend adapter base classes and common types."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    """Common event emitted by all backends."""
    type: str          # "text", "tool_use", "tool_result", "error", "rate_limit", "complete"
    content: str       # text content or tool name
    detail: str = ""   # tool args, error message, etc.
    raw: dict = field(default_factory=dict)  # backend-specific data


@dataclass
class SessionInfo:
    """Session metadata reported by backends."""
    session_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    context_limit: int | None = None


@dataclass
class CommandInfo:
    """Description of a CLI command supported by a backend."""
    name: str
    description: str
    backend: str


class Backend(ABC):
    """Abstract base for CLI backend adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name, e.g. 'claude', 'codex', 'gemini'."""

    @abstractmethod
    async def start_session(
        self, cwd: str, system_prompt: str, model: str
    ) -> str:
        """Start a new CLI session. Returns session ID."""

    @abstractmethod
    async def resume_session(self, session_id: str) -> bool:
        """Try to resume a session. Returns True if successful."""

    @abstractmethod
    async def query(
        self,
        session_id: str,
        prompt: str,
        allowed_tools: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Send a prompt and yield events as they arrive."""

    @abstractmethod
    async def cancel(self, session_id: str) -> None:
        """Cancel an in-flight query."""

    @abstractmethod
    async def get_session_info(self, session_id: str) -> SessionInfo:
        """Get token counts, model info for a session."""

    def capabilities(self) -> set[str]:
        """Return set of optional capabilities this backend supports."""
        return set()

    async def cli_passthrough(self, session_id: str, command: str) -> str:
        """Pass a CLI command through to the backend. Returns output text."""
        return f"CLI passthrough not supported by {self.name} backend"

    def supported_commands(self) -> list[CommandInfo]:
        """Return list of CLI commands this backend supports."""
        return []

    def terminal_resume_command(self, session_id: str) -> str | None:
        """Return the terminal command to resume this session, or None."""
        return None
