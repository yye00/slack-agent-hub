"""Gemini CLI backend adapter."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

from backends.base import Backend, CommandInfo, Event, SessionInfo
from backends.subprocess_utils import build_env, run_cli_query

logger = logging.getLogger(__name__)


class GeminiBackend(Backend):
    """Adapter for Google Gemini CLI (gemini -p --output-format stream-json)."""

    def __init__(self) -> None:
        self._session_config: dict = {}

    @property
    def name(self) -> str:
        return "gemini"

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
        return ""  # Populated by first query result

    async def resume_session(self, session_id: str, cwd: str = "", model: str = "") -> bool:
        if not session_id:
            return False
        self._session_config["resume_id"] = session_id
        if cwd:
            self._session_config["cwd"] = cwd
        if model:
            self._session_config["model"] = model
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
            for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS")
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
            logger.error("Gemini CLI error: %s", exc)
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
            CommandInfo("/compact", "Compact conversation context", "gemini"),
        ]

    def terminal_resume_command(self, session_id: str) -> str | None:
        if session_id:
            return f"gemini -r {session_id}"
        return None

    def _build_command(self, prompt: str) -> list[str]:
        cmd = ["gemini", "-p", prompt, "--output-format", "stream-json", "--yolo"]
        model = self._session_config.get("model")
        if model:
            cmd.extend(["-m", model])
        resume_id = self._session_config.get("resume_id")
        if resume_id:
            cmd.extend(["-r", resume_id])
        return cmd

    def _parse_line(self, line: str, response_parts: list[str]) -> Event | None:
        """Parse a single JSON line from Gemini stream-json output."""
        if not line.strip():
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON line: %s", line[:100])
            return None

        event_type = data.get("type", "")

        if event_type == "init":
            # Capture session ID from init event
            sid = data.get("session_id", "")
            if sid:
                self._session_config["session_id"] = sid
            return None

        if event_type == "message" and data.get("role") == "assistant":
            content = data.get("content", "")
            response_parts.append(content)
            return Event(type="text", content=content, raw={"block": "text"})

        elif event_type == "tool_call":
            return Event(
                type="tool_use",
                content=data.get("name", "unknown"),
                detail=str(data.get("args", {}))[:200],
                raw={"tool_id": data.get("id", "")},
            )

        elif event_type == "result":
            stats = data.get("stats", {})
            session_id = self._session_config.get("session_id", "")
            return Event(
                type="complete",
                content="\n".join(response_parts),
                detail=session_id,
                raw={
                    "session_id": session_id,
                    "cost_usd": data.get("cost_usd"),
                    "input_tokens": stats.get("input_tokens"),
                    "output_tokens": stats.get("output_tokens"),
                },
            )

        elif event_type == "error":
            return Event(type="error", content=data.get("message", str(data)))

        return None
