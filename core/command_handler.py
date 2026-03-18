"""Hub command execution — all !commands dispatched here."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from features.memory import read_memory
from slack_io.messages import chunk_response

if TYPE_CHECKING:
    from core.agent import Agent
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_io.posting import SlackPoster
    from storage.db import Database

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles all hub !commands."""

    def __init__(
        self,
        agents: dict[str, Agent],
        db: Database,
        slack_client: AsyncWebClient,
        poster: SlackPoster,
    ):
        self._agents = agents
        self._db = db
        self._slack = slack_client
        self._poster = poster

    async def _reply(self, channel_id, text, thread_ts=None):
        """Send a branded reply via the poster."""
        await self._poster.post(channel=channel_id, text=text, thread_ts=thread_ts)

    async def handle(
        self,
        command: str,
        args: list[str],
        options: dict[str, str],
        channel_id: str,
        thread_ts: str | None,
        target_agent: str,
        user: str,
    ):
        """Dispatch a command to the appropriate handler."""
        handler = getattr(self, f"_cmd_{command}", None)
        if handler:
            await handler(args, options, channel_id, thread_ts, target_agent, user)
        else:
            await self._reply(
                channel_id,
                f"Unknown command: !{command}. Type !help for available commands.",
                thread_ts,
            )

    async def _cmd_agents(self, args, options, channel_id, thread_ts, target_agent, user):
        lines = []
        for name, agent in self._agents.items():
            status_icon = {"active": "🟢", "paused": "🟡"}.get(agent.status, "🔴")
            lines.append(f"{status_icon} {agent.display_name} ({agent.backend.name}) │ {agent.status}")
        text = "\n".join(lines) if lines else "No agents configured."
        await self._reply(channel_id, text, thread_ts)

    async def _cmd_status(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            session_display = "none"
            if agent.current_session_id:
                session = await self._db.get_session(agent.current_session_id)
                sname = session.get("name", "") if session else ""
                if sname:
                    session_display = f"{sname} (`{agent.current_session_id[:8]}…`)"
                else:
                    session_display = f"`{agent.current_session_id[:8]}…`"
            text = (
                f"*{agent.display_name}*\n"
                f"Backend: {agent.backend.name}\n"
                f"Model: {agent.config.model}\n"
                f"Profile: {agent.config.profile}\n"
                f"Status: {agent.status}\n"
                f"Session: {session_display}\n"
                f"CWD: {agent.config.cwd}"
            )
            await self._reply(channel_id, text, thread_ts)

    async def _cmd_pause(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            agent.pause()
            await self._db.update_agent_status(name, "paused")
            await self._reply(channel_id, f"⏸️ {agent.display_name} paused.", thread_ts)

    async def _cmd_unpause(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            agent.unpause()
            await self._db.update_agent_status(name, "active")
            await self._reply(channel_id, f"▶️ {agent.display_name} resumed.", thread_ts)

    async def _cmd_cancel(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent and agent._active_query_task:
            agent._active_query_task.cancel()
            await self._reply(channel_id, f"🛑 Cancelled query for {agent.display_name}.", thread_ts)

    @staticmethod
    def _format_age(iso_ts: str) -> str:
        """Convert ISO timestamp to human-readable age like '2h ago'."""
        try:
            created = datetime.fromisoformat(iso_ts)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - created
            secs = int(delta.total_seconds())
            if secs < 60:
                return f"{secs}s ago"
            elif secs < 3600:
                return f"{secs // 60}m ago"
            elif secs < 86400:
                return f"{secs // 3600}h ago"
            else:
                return f"{secs // 86400}d ago"
        except (ValueError, TypeError):
            return "?"

    async def _cmd_sessions(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        if name:
            sessions = await self._db.list_sessions(name)
            if sessions:
                lines = []
                for s in sessions:
                    session_name = s.get("name") or "unnamed"
                    age = self._format_age(s.get("created_at", ""))
                    status = "archived" if s.get("archived") else "active"
                    last_active = s.get("last_active") or "never"
                    if last_active != "never":
                        last_active = self._format_age(last_active)
                    model = f" ({s['model']})" if s.get("model") else ""
                    lines.append(
                        f"  `{s['id'][:8]}` {session_name}{model} │ {status} │ {age} │ last: {last_active}"
                    )
                text = f"Sessions for {name}:\n" + "\n".join(lines)
            else:
                text = f"No sessions for {name}."
            await self._reply(channel_id, text, thread_ts)

    async def _cmd_new(self, args, options, channel_id, thread_ts, target_agent, user):
        agent = self._agents.get(target_agent)
        if agent:
            agent.current_session_id = None
            label = args[0] if args else None
            model = options.get("model")
            msg = f"🆕 Fresh session for {agent.display_name}."
            if label:
                msg += f" Label: {label}"
            if model:
                msg += f" Model: {model}"
            await self._reply(channel_id, msg, thread_ts)

    async def _cmd_pin(self, args, options, channel_id, thread_ts, target_agent, user):
        text_to_pin = " ".join(args)
        if text_to_pin:
            await self._db.create_pin(channel_id, text_to_pin, user)
            await self._reply(channel_id, f"📌 Pinned: {text_to_pin}", thread_ts)

    async def _cmd_pins(self, args, options, channel_id, thread_ts, target_agent, user):
        pins = await self._db.list_pins(channel_id)
        if pins:
            lines = [f"  [{p['id']}] {p['content']}" for p in pins]
            text = "Pinned context:\n" + "\n".join(lines)
        else:
            text = "No pins in this channel."
        await self._reply(channel_id, text, thread_ts)

    async def _cmd_unpin(self, args, options, channel_id, thread_ts, target_agent, user):
        if args:
            try:
                pin_id = int(args[0])
                await self._db.delete_pin(pin_id)
                await self._reply(channel_id, f"📌 Removed pin {pin_id}.", thread_ts)
            except ValueError:
                await self._reply(channel_id, "Usage: !unpin <id>", thread_ts)

    async def _cmd_memory(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            mem = read_memory(agent.config.cwd)
            text = mem if mem else "No memory recorded."
            chunks = chunk_response(text)
            for chunk in chunks:
                await self._reply(channel_id, chunk, thread_ts)

    async def _cmd_resume(self, args, options, channel_id, thread_ts, target_agent, user):
        """Resume a previous session by ID."""
        agent = self._agents.get(target_agent)
        if not agent:
            return
        if not args:
            await self._reply(channel_id, "Usage: !resume <session_id>", thread_ts)
            return
        session_id = args[0]
        ok = await agent.backend.resume_session(session_id)
        if ok:
            agent.current_session_id = session_id
            await self._reply(
                channel_id,
                f"▶️ Resumed session `{session_id[:8]}…` for {agent.display_name}.",
                thread_ts,
            )
        else:
            await self._reply(channel_id, f"Failed to resume session `{session_id}`.", thread_ts)

    async def _cmd_refresh(self, args, options, channel_id, thread_ts, target_agent, user):
        """Start a fresh session, keeping the current one in history."""
        agent = self._agents.get(target_agent)
        if not agent:
            return
        old_id = agent.current_session_id
        agent.current_session_id = None
        msg = f"🔄 Refreshed {agent.display_name}."
        if old_id:
            msg += f" Previous session: `{old_id[:8]}…`"
        await self._reply(channel_id, msg, thread_ts)

    async def _cmd_cost(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        if name and name != "all":
            costs = await self._db.get_agent_costs(name)
            total_in = sum(c["input_tokens"] for c in costs)
            total_out = sum(c["output_tokens"] for c in costs)
            text = f"Cost for {name}: {total_in:,} input, {total_out:,} output tokens"
            await self._reply(channel_id, text, thread_ts)

    async def _cmd_help(self, args, options, channel_id, thread_ts, target_agent, user):
        help_text = (
            "*Agent Lifecycle:* !agents, !status, !pause, !unpause, !cancel\n"
            "*Sessions:* !new, !sessions, !resume, !refresh\n"
            "*Memory:* !memory, !pin, !pins, !unpin\n"
            "*Cost:* !cost\n"
            "*CLI:* > /command (passthrough to backend)\n"
        )
        await self._reply(channel_id, help_text, thread_ts)
