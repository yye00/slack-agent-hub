"""Codex CLI backend adapter."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

from backends.base import Backend, CommandInfo, Event, SessionInfo
from backends.subprocess_utils import build_env, run_cli_query

logger = logging.getLogger(__name__)


class CodexBackend(Backend):
    """Adapter for OpenAI Codex CLI (codex exec --json)."""

    def __init__(self) -> None:
        self._session_config: dict = {}

    @property
    def name(self) -> str:
        return "codex"

    def capabilities(self) -> set[str]:
        return {"session_resume", "streaming"}

    async def start_session(
        self, cwd: str, system_prompt: str, model: str
    ) -> str:
        self._session_config = {
            "cwd": cwd,
            "system_prompt": system_prompt,
            "model": model,
        }
        return ""

    async def resume_session(self, session_id: str) -> bool:
        if not session_id:
            return False
        self._session_config["resume_id"] = session_id
        return True

    async def query(
        self,
        session_id: str,
        prompt: str,
        allowed_tools: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        cmd = self._build_command(prompt)
        env = build_env({
            k: os.environ[k]
            for k in ("OPENAI_API_KEY", "CODEX_API_KEY")
            if k in os.environ
        })
        cwd = self._session_config.get("cwd")

        response_parts: list[str] = []
        try:
            async for line in run_cli_query(cmd, env=env, cwd=cwd):
                event = self._parse_line(line, response_parts)
                if event:
                    yield event
        except Exception as exc:
            logger.error("Codex CLI error: %s", exc)
            yield Event(type="error", content=str(exc))

    async def cancel(self, session_id: str) -> None:
        pass  # Handled by asyncio task cancellation

    async def get_session_info(self, session_id: str) -> SessionInfo:
        return SessionInfo(session_id=session_id)

    async def cli_passthrough(self, session_id: str, command: str) -> str:
        if not session_id:
            return "No active session. Send a message first."
        parts = []
        async for event in self.query(session_id, command):
            if event.type == "text":
                parts.append(event.content)
        return "\n".join(parts) if parts else "(no output)"

    def supported_commands(self) -> list[CommandInfo]:
        return [
            CommandInfo("/model", "Switch model", "codex"),
        ]

    def terminal_resume_command(self, session_id: str) -> str | None:
        if session_id:
            return f"codex exec resume {session_id}"
        return None

    def _build_command(self, prompt: str) -> list[str]:
        resume_id = self._session_config.get("resume_id")
        if resume_id:
            # codex exec resume SESSION_ID PROMPT — supports both args
            cmd = [
                "codex", "exec", "resume", resume_id,
                "--json", "--dangerously-bypass-approvals-and-sandbox",
            ]
        else:
            cmd = [
                "codex", "exec",
                "--json", "--dangerously-bypass-approvals-and-sandbox",
            ]

        model = self._session_config.get("model")
        if model:
            cmd.extend(["-m", model])

        cwd = self._session_config.get("cwd")
        if cwd:
            cmd.extend(["-C", cwd])

        # Prompt is always appended — codex exec resume accepts it as a positional arg
        cmd.append(prompt)
        return cmd

    def _parse_line(self, line: str, response_parts: list[str]) -> Event | None:
        """Parse a single JSONL line from Codex exec output."""
        if not line.strip():
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON line: %s", line[:100])
            return None

        event_type = data.get("type", "")

        if event_type == "message" and data.get("role") == "assistant":
            content = data.get("content", "")
            response_parts.append(content)
            return Event(type="text", content=content, raw={"block": "text"})

        elif event_type == "function_call":
            return Event(
                type="tool_use",
                content=data.get("name", "unknown"),
                detail=str(data.get("arguments", ""))[:200],
                raw={"tool_id": data.get("id", "")},
            )

        elif event_type == "completion":
            usage = data.get("usage", {})
            session_id = data.get("session_id", "")
            return Event(
                type="complete",
                content="\n".join(response_parts),
                detail=session_id,
                raw={
                    "session_id": session_id,
                    "cost_usd": data.get("cost_usd"),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                },
            )

        elif event_type == "error":
            return Event(type="error", content=data.get("message", str(data)))

        return None
