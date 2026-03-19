"""Claude CLI backend adapter using claude-agent-sdk."""

import logging
import os
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, query as claude_query
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from backends.base import Backend, CommandInfo, Event, SessionInfo

logger = logging.getLogger(__name__)

# Env vars that prevent Claude from running inside another Claude session
_NESTING_VARS = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION"}


def _clean_env() -> dict[str, str]:
    """Return env overrides that suppress nesting detection.

    The SDK merges os.environ with options.env, so we must explicitly
    blank out the nesting vars rather than omitting them.
    """
    return {k: "" for k in _NESTING_VARS}


def _stderr_handler(line: str) -> None:
    """Log stderr from the Claude CLI subprocess."""
    logger.info(f"claude-cli stderr: {line.rstrip()}")


class ClaudeBackend(Backend):
    """Adapter for Claude Code CLI via claude-agent-sdk."""

    def __init__(self):
        super().__init__()
        self._permission_mode: str = "default"

    @property
    def name(self) -> str:
        return "claude"

    def capabilities(self) -> set[str]:
        return {"session_resume", "compact", "cost_tracking", "streaming"}

    async def start_session(
        self, cwd: str, system_prompt: str, model: str
    ) -> str:
        """Start a new Claude session. Returns session ID.

        The session ID is obtained from the first query response.
        We store the options for later use.
        """
        self._pending_options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            cwd=cwd,
            permission_mode=self._permission_mode,
            env=_clean_env(),
            stderr=_stderr_handler,
        )
        return ""  # Will be populated by first query

    async def resume_session(self, session_id: str) -> bool:
        """Resume a Claude session by ID."""
        if not session_id:
            return False
        self._pending_options = ClaudeAgentOptions(
            resume=session_id,
            permission_mode=self._permission_mode,
            env=_clean_env(),
            stderr=_stderr_handler,
        )
        return True

    async def query(
        self,
        session_id: str,
        prompt: str,
        allowed_tools: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Send prompt to Claude and yield events."""
        options = getattr(self, "_pending_options", None)
        if options is None:
            # Re-use the last successful options with updated resume
            last = getattr(self, "_last_options", None)
            if last and session_id:
                options = ClaudeAgentOptions(
                    resume=session_id,
                    model=last.model,
                    cwd=last.cwd,
                    permission_mode=last.permission_mode,
                    env=_clean_env(),
                    stderr=_stderr_handler,
                )
            else:
                options = ClaudeAgentOptions(
                    resume=session_id,
                    permission_mode=self._permission_mode,
                    env=_clean_env(),
                    stderr=_stderr_handler,
                )

        if allowed_tools:
            options.allowed_tools = allowed_tools

        # Save for future re-use
        self._last_options = options

        response_text_parts: list[str] = []
        real_session_id = session_id

        try:
            async for message in claude_query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text_parts.append(block.text)
                            yield Event(
                                type="text",
                                content=block.text,
                                raw={"block": "text"},
                            )
                        elif isinstance(block, ToolUseBlock):
                            yield Event(
                                type="tool_use",
                                content=block.name,
                                detail=str(block.input)[:200],
                                raw={"tool_id": block.id},
                            )
                elif isinstance(message, ResultMessage):
                    real_session_id = getattr(message, "session_id", session_id)
                    yield Event(
                        type="complete",
                        content="\n".join(response_text_parts),
                        detail=real_session_id,
                        raw={
                            "session_id": real_session_id,
                            "cost_usd": getattr(message, "total_cost_usd", None),
                            "duration_ms": getattr(message, "duration_ms", None),
                            "num_turns": getattr(message, "num_turns", None),
                            "input_tokens": getattr(message, "input_tokens", None),
                            "output_tokens": getattr(message, "output_tokens", None),
                        },
                    )
        finally:
            self._pending_options = None

    async def cancel(self, session_id: str) -> None:
        """Cancel is handled externally by cancelling the asyncio task."""
        pass

    async def get_session_info(self, session_id: str) -> SessionInfo:
        """Get session info. Token tracking is approximate from events."""
        return SessionInfo(session_id=session_id)

    async def cli_passthrough(self, session_id: str, command: str) -> str:
        """Pass a CLI slash command to the Claude session."""
        if not session_id:
            return "No active session. Send a message first."
        parts = []
        async for event in self.query(session_id, command):
            if event.type == "text":
                parts.append(event.content)
        return "\n".join(parts) if parts else "(no output)"

    def supported_commands(self) -> list[CommandInfo]:
        return [
            CommandInfo("/compact", "Compact conversation context", "claude"),
            CommandInfo("/model", "Switch model", "claude"),
            CommandInfo("/cost", "Show token usage and cost", "claude"),
            CommandInfo("/help", "Show available commands", "claude"),
        ]

    def terminal_resume_command(self, session_id: str) -> str | None:
        if session_id:
            return f"claude --resume {session_id}"
        return None
