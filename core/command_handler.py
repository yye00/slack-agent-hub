"""Hub command execution — all !commands dispatched here."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from features.memory import read_memory
from slack_io.messages import chunk_response

if TYPE_CHECKING:
    from core.agent import Agent
    from slack_sdk.web.async_client import AsyncWebClient
    from storage.db import Database

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles all hub !commands."""

    def __init__(
        self,
        agents: dict[str, Agent],
        db: Database,
        slack_client: AsyncWebClient,
    ):
        self._agents = agents
        self._db = db
        self._slack = slack_client

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
            await self._slack.chat_postMessage(
                channel=channel_id,
                text=f"Unknown command: !{command}. Type !help for available commands.",
                thread_ts=thread_ts,
            )

    async def _cmd_agents(self, args, options, channel_id, thread_ts, target_agent, user):
        lines = []
        for name, agent in self._agents.items():
            status_icon = {"active": "🟢", "paused": "🟡"}.get(agent.status, "🔴")
            lines.append(f"{status_icon} {agent.display_name} ({agent.backend.name}) │ {agent.status}")
        text = "\n".join(lines) if lines else "No agents configured."
        await self._slack.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)

    async def _cmd_status(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            text = (
                f"**{agent.display_name}**\n"
                f"Backend: {agent.backend.name}\n"
                f"Model: {agent.config.model}\n"
                f"Profile: {agent.config.profile}\n"
                f"Status: {agent.status}\n"
                f"Session: {agent.current_session_id or 'none'}\n"
                f"CWD: {agent.config.cwd}"
            )
            await self._slack.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)

    async def _cmd_pause(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            agent.pause()
            await self._db.update_agent_status(name, "paused")
            await self._slack.chat_postMessage(
                channel=channel_id, text=f"⏸️ {agent.display_name} paused.", thread_ts=thread_ts
            )

    async def _cmd_unpause(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            agent.unpause()
            await self._db.update_agent_status(name, "active")
            await self._slack.chat_postMessage(
                channel=channel_id, text=f"▶️ {agent.display_name} resumed.", thread_ts=thread_ts
            )

    async def _cmd_cancel(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent and agent._active_query_task:
            agent._active_query_task.cancel()
            await self._slack.chat_postMessage(
                channel=channel_id, text=f"🛑 Cancelled query for {agent.display_name}.", thread_ts=thread_ts
            )

    async def _cmd_sessions(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        if name:
            sessions = await self._db.list_sessions(name)
            if sessions:
                lines = []
                for s in sessions:
                    label = f" [{s['label']}]" if s.get("label") else ""
                    model = f" ({s['model']})" if s.get("model") else ""
                    lines.append(f"  {s['id'][:8]}{label}{model} — {s.get('created_at', '?')}")
                text = f"Sessions for {name}:\n" + "\n".join(lines)
            else:
                text = f"No sessions for {name}."
            await self._slack.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)

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
            await self._slack.chat_postMessage(channel=channel_id, text=msg, thread_ts=thread_ts)

    async def _cmd_pin(self, args, options, channel_id, thread_ts, target_agent, user):
        text_to_pin = " ".join(args)
        if text_to_pin:
            await self._db.create_pin(channel_id, text_to_pin, user)
            await self._slack.chat_postMessage(
                channel=channel_id, text=f"📌 Pinned: {text_to_pin}", thread_ts=thread_ts
            )

    async def _cmd_pins(self, args, options, channel_id, thread_ts, target_agent, user):
        pins = await self._db.list_pins(channel_id)
        if pins:
            lines = [f"  [{p['id']}] {p['content']}" for p in pins]
            text = "Pinned context:\n" + "\n".join(lines)
        else:
            text = "No pins in this channel."
        await self._slack.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)

    async def _cmd_unpin(self, args, options, channel_id, thread_ts, target_agent, user):
        if args:
            try:
                pin_id = int(args[0])
                await self._db.delete_pin(pin_id)
                await self._slack.chat_postMessage(
                    channel=channel_id, text=f"📌 Removed pin {pin_id}.", thread_ts=thread_ts
                )
            except ValueError:
                await self._slack.chat_postMessage(
                    channel=channel_id, text="Usage: !unpin <id>", thread_ts=thread_ts
                )

    async def _cmd_memory(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if agent:
            mem = read_memory(agent.config.cwd)
            text = mem if mem else "No memory recorded."
            chunks = chunk_response(text)
            for chunk in chunks:
                await self._slack.chat_postMessage(
                    channel=channel_id, text=chunk, thread_ts=thread_ts
                )

    async def _cmd_cost(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        if name and name != "all":
            costs = await self._db.get_agent_costs(name)
            total_in = sum(c["input_tokens"] for c in costs)
            total_out = sum(c["output_tokens"] for c in costs)
            text = f"Cost for {name}: {total_in:,} input, {total_out:,} output tokens"
            await self._slack.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)

    async def _cmd_help(self, args, options, channel_id, thread_ts, target_agent, user):
        help_text = (
            "*Agent Lifecycle:* !agents, !status, !pause, !unpause, !restart, !reload\n"
            "*Sessions:* !new, !sessions, !resume, !refresh, !cancel\n"
            "*Context:* !context, !search, !history\n"
            "*Memory:* !memory, !pin, !pins, !unpin\n"
            "*Monitors:* !watch, !monitor, !monitors, !stop\n"
            "*Cost:* !cost\n"
            "*Federation:* !roster, !dashboard\n"
            "*CLI:* > /command (passthrough to backend)\n"
        )
        await self._slack.chat_postMessage(channel=channel_id, text=help_text, thread_ts=thread_ts)
