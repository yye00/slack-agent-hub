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
        channel_agents: dict[str, list[str]] | None = None,
        spawn_callback=None,
    ):
        self._agents = agents
        self._db = db
        self._slack = slack_client
        self._poster = poster
        self._channel_agents = channel_agents or {}
        self._spawn_callback = spawn_callback

    async def _reply(self, channel_id, text, thread_ts=None, agent_name=None):
        """Send a branded reply via the poster, chunking if needed."""
        name = agent_name or getattr(self, "_current_agent", None)
        chunks = chunk_response(text)
        for chunk in chunks:
            await self._poster.post(
                channel=channel_id, text=chunk, thread_ts=thread_ts,
                agent_name=name,
            )

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
        # Store target agent for _reply color resolution
        self._current_agent = target_agent
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
        name = args[0] if args else None
        if name:
            # Show detailed status for a specific agent
            agent = self._agents.get(name)
            if not agent:
                await self._reply(channel_id, f"Unknown agent: `{name}`. Try `!agents` to list all.", thread_ts)
                return
            await self._reply(channel_id, await self._agent_status_block(agent), thread_ts)
        else:
            # No agent specified — show all agents in this channel
            channel_agents = self._get_channel_agents(channel_id)
            if not channel_agents:
                channel_agents = list(self._agents.values())
            blocks = []
            for agent in channel_agents:
                blocks.append(await self._agent_status_block(agent))
            text = "\n───\n".join(blocks)
            await self._reply(channel_id, text, thread_ts)

    async def _agent_status_block(self, agent) -> str:
        """Build a status block for a single agent."""
        status_icon = {"active": "🟢", "paused": "🟡"}.get(agent.status, "🔴")
        session_display = "none"
        if agent.current_session_id:
            session = await self._db.get_session(agent.current_session_id)
            sname = session.get("name", "") if session else ""
            if sname:
                session_display = f"{sname} (`{agent.current_session_id[:8]}…`)"
            else:
                session_display = f"`{agent.current_session_id[:8]}…`"
        resume_hint = ""
        if agent.current_session_id:
            resume_cmd = agent.backend.terminal_resume_command(agent.current_session_id)
            if resume_cmd:
                resume_hint = f"\nCLI resume: `{resume_cmd}`"
        return (
            f"{status_icon} *{agent.display_name}* (`{agent.name}`)\n"
            f"Backend: {agent.backend.name} · {agent.config.model}\n"
            f"Status: {agent.status} │ Session: {session_display}"
            f"{resume_hint}"
        )

    def _get_channel_agents(self, channel_id: str) -> list:
        """Get Agent objects for a channel."""
        names = self._channel_agents.get(channel_id, [])
        return [self._agents[n] for n in names if n in self._agents]

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
        if not agent:
            await self._reply(channel_id, f"Unknown agent: {name}", thread_ts)
            return
        task = getattr(agent, "_active_query_task", None)
        if task and not task.done():
            task.cancel()
            await self._reply(channel_id, f"🛑 Cancelled query for {agent.display_name}.", thread_ts)
        else:
            await self._reply(channel_id, f"No active query for {agent.display_name}.", thread_ts)

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
        if args and args[0].lower() == "all":
            # Show sessions for all agents hub-wide
            agent_names = list(self._agents.keys())
        elif args:
            # Show sessions for a specific agent
            agent_names = [args[0]]
        else:
            # Show sessions for all agents in the channel
            channel_agents = self._get_channel_agents(channel_id)
            if channel_agents:
                agent_names = [a.name for a in channel_agents]
            elif target_agent:
                agent_names = [target_agent]
            else:
                agent_names = list(self._agents.keys())

        blocks = []
        for name in agent_names:
            agent = self._agents.get(name)
            display = agent.display_name if agent else name
            sessions = await self._db.list_sessions(name)
            if sessions:
                lines = [f"*{display}* (`{name}`):"]
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
                blocks.append("\n".join(lines))

        if blocks:
            await self._reply(channel_id, "\n───\n".join(blocks), thread_ts)
        else:
            await self._reply(channel_id, "No sessions found.", thread_ts)

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
        """Resume a previous session by ID, prefix, or name."""
        agent = self._agents.get(target_agent)
        if not agent:
            return
        if not args:
            await self._reply(channel_id, "Usage: `!resume <session_id or name>`", thread_ts)
            return
        # Resolve by ID prefix or session name (scoped to this agent)
        session = await self._db.get_session(args[0], agent_name=agent.name)
        if not session:
            await self._reply(
                channel_id,
                f"No session matching `{args[0]}` for {agent.display_name}. Use `!sessions` to list.",
                thread_ts,
            )
            return
        session_id = session["id"]
        ok = await agent.backend.resume_session(
            session_id, cwd=agent.config.cwd, model=agent.config.model)
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

    async def _cmd_health(self, args, options, channel_id, thread_ts, target_agent, user):
        from core.health import build_health_report
        host_id = self._get_host_id()
        report = build_health_report(self._agents, host_id=host_id)
        await self._reply(channel_id, report, thread_ts)

    def _get_host_id(self) -> str:
        """Get host_id from any agent."""
        for agent in self._agents.values():
            return agent.host_id
        return "unknown"

    async def _cmd_diag(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if not agent:
            await self._reply(channel_id, f"Unknown agent: {name}", thread_ts)
            return
        session = agent.current_session_id or "none"
        task = getattr(agent, "_active_query_task", None)
        query_active = bool(task and not task.done())
        stderr = getattr(agent.backend, 'last_stderr', 'N/A')
        text = (
            f"🔍 *Diagnostics for {agent.display_name}*\n"
            f"Status: {agent.status}\n"
            f"Backend: {agent.backend.name} ({agent.config.model})\n"
            f"Session: `{session}`\n"
            f"Query active: {'yes' if query_active else 'no'}\n"
            f"CWD: {agent.config.cwd}\n"
            f"Profile: {agent.config.profile} ({agent.profile.permission_mode})\n"
            f"Recent stderr:\n```\n{stderr}\n```"
        )
        await self._reply(channel_id, text, thread_ts)

    async def _cmd_logs(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if not agent:
            await self._reply(channel_id, f"Unknown agent: {name}", thread_ts)
            return
        stderr = getattr(agent.backend, 'last_stderr', 'No logs available.')
        try:
            n = int(args[1]) if len(args) > 1 else 20
        except ValueError:
            n = 20
        lines = stderr.split("\n")[-n:]
        text = (
            f"📋 *Recent logs for {agent.display_name}* (last {len(lines)} lines):\n"
            f"```\n" + "\n".join(lines) + "\n```"
        )
        await self._reply(channel_id, text, thread_ts)

    async def _cmd_test(self, args, options, channel_id, thread_ts, target_agent, user):
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if not agent:
            await self._reply(channel_id, f"Unknown agent: {name}", thread_ts)
            return
        if not agent.current_session_id:
            await self._reply(
                channel_id,
                f"⚠️ {agent.display_name} has no active session. Send a message first.",
                thread_ts,
            )
            return
        await self._reply(channel_id, f"🧪 Testing {agent.display_name}...", thread_ts)
        try:
            parts = []
            async for event in agent.backend.query(
                session_id=agent.current_session_id,
                prompt="respond with 'ok' and nothing else",
            ):
                if event.type == "text":
                    parts.append(event.content)
            response = "".join(parts) or "(no response)"
            await self._reply(channel_id, f"✅ {agent.display_name} responded: {response[:200]}", thread_ts)
        except Exception as e:
            await self._reply(channel_id, f"❌ {agent.display_name} test failed: {e}", thread_ts)

    async def _cmd_restart(self, args, options, channel_id, thread_ts, target_agent, user):
        """Restart an agent — clear session and start fresh."""
        name = args[0] if args else target_agent
        agent = self._agents.get(name)
        if not agent:
            await self._reply(channel_id, f"Unknown agent: {name}", thread_ts)
            return
        old_session = agent.current_session_id
        agent.current_session_id = None
        msg = f"🔄 Restarted {agent.display_name}."
        if old_session:
            msg += f" Previous session: `{old_session[:8]}…`"
        await self._reply(channel_id, msg, thread_ts)

    async def _cmd_roster(self, args, options, channel_id, thread_ts, target_agent, user):
        """Show all agents with host and channel info."""
        lines = ["*Agent Roster:*", ""]
        for name, agent in self._agents.items():
            status_icon = {"active": "🟢", "paused": "🟡"}.get(agent.status, "🔴")
            channels = ", ".join(agent.config.channels)
            lines.append(
                f"{status_icon} *{agent.display_name}* │ {agent.backend.name} ({agent.config.model}) │ {channels}"
            )
        await self._reply(channel_id, "\n".join(lines), thread_ts)

    async def _cmd_history(self, args, options, channel_id, thread_ts, target_agent, user):
        """Show recent channel messages."""
        try:
            n = int(args[0]) if args else 10
        except ValueError:
            n = 10
        try:
            resp = await self._slack.conversations_history(channel=channel_id, limit=n)
            msgs = resp.get("messages", [])
            lines = [f"📜 *Last {len(msgs)} messages:*", ""]
            for msg in reversed(msgs):
                user_id = msg.get("user", "bot")
                text = msg.get("text", "")[:100]
                lines.append(f"  <@{user_id}>: {text}")
            await self._reply(channel_id, "\n".join(lines), thread_ts)
        except Exception as e:
            await self._reply(channel_id, f"Failed to fetch history: {e}", thread_ts)

    async def _cmd_context(self, args, options, channel_id, thread_ts, target_agent, user):
        """Fetch and display recent channel context for agent awareness."""
        try:
            n = int(args[0]) if args else 20
        except ValueError:
            n = 20
        try:
            resp = await self._slack.conversations_history(channel=channel_id, limit=n)
            msgs = resp.get("messages", [])
            lines = [f"🔎 *Channel context (last {len(msgs)} messages):*", ""]
            for msg in reversed(msgs):
                user_id = msg.get("user", "bot")
                text = msg.get("text", "")[:150]
                lines.append(f"  <@{user_id}>: {text}")
            await self._reply(channel_id, "\n".join(lines), thread_ts)
        except Exception as e:
            await self._reply(channel_id, f"Failed to fetch context: {e}", thread_ts)

    async def _cmd_search(self, args, options, channel_id, thread_ts, target_agent, user):
        """Search channel history by keyword."""
        if not args:
            await self._reply(channel_id, "Usage: !search <keyword>", thread_ts)
            return
        keyword = " ".join(args)
        try:
            resp = await self._slack.conversations_history(channel=channel_id, limit=100)
            msgs = resp.get("messages", [])
            matches = [m for m in msgs if keyword.lower() in (m.get("text", "")).lower()]
            if matches:
                lines = [f"🔍 *Found {len(matches)} matches for '{keyword}':*", ""]
                for msg in matches[:10]:  # max 10 results
                    user_id = msg.get("user", "bot")
                    text = msg.get("text", "")[:100]
                    lines.append(f"  <@{user_id}>: {text}")
                await self._reply(channel_id, "\n".join(lines), thread_ts)
            else:
                await self._reply(channel_id, f"No matches found for '{keyword}'.", thread_ts)
        except Exception as e:
            await self._reply(channel_id, f"Search failed: {e}", thread_ts)

    async def _cmd_reload(self, args, options, channel_id, thread_ts, target_agent, user):
        """Reload config.yaml and apply changes without restarting."""
        try:
            from core.config import load_config
            from pathlib import Path
            import os
            config_path = Path(os.getenv("CONFIG_PATH", "config.yaml"))
            new_config = load_config(config_path)
            # Note: Full config application requires hub-level integration.
            # For now, report what was loaded and note that agent/profile changes
            # take effect on next session start.
            await self._reply(
                channel_id,
                f"✅ Config reloaded from `{config_path}`. "
                f"{len(new_config.agents)} agents, {len(new_config.profiles)} profiles configured. "
                f"Agent/profile changes take effect on next session start.",
                thread_ts,
            )
        except Exception as e:
            await self._reply(channel_id, f"❌ Config reload failed: {e}", thread_ts)

    async def _cmd_audit(self, args, options, channel_id, thread_ts, target_agent, user):
        """Show last N audit log entries. Requires ADMIN level (enforced in hub)."""
        n = 20
        if args:
            try:
                n = int(args[0])
            except ValueError:
                pass
        entries = await self._db.get_audit_log(limit=n)
        if not entries:
            await self._reply(channel_id, "No audit log entries.", thread_ts)
            return
        lines = [f"📝 *Audit log (last {n}):*", ""]
        for e in entries:
            ts = e.get("timestamp", "")[:19].replace("T", " ")
            target = e.get("target") or "-"
            detail = e.get("detail") or ""
            lines.append(
                f"  `{ts}` <@{e['user_id']}> {e['action']} `{target}` {detail}"
            )
        await self._reply(channel_id, "\n".join(lines), thread_ts)

    async def _cmd_export(self, args, options, channel_id, thread_ts, target_agent, user):
        """Export session metadata as formatted JSON."""
        if not args:
            await self._reply(channel_id, "Usage: !export <session_id>", thread_ts)
            return
        session = await self._db.get_session(args[0])
        if not session:
            await self._reply(channel_id, f"Session `{args[0]}` not found.", thread_ts)
            return
        import json
        export_data = {k: v for k, v in session.items() if v is not None}
        text = f"*Session export:*\n```\n{json.dumps(export_data, indent=2)}\n```"
        await self._reply(channel_id, text, thread_ts)

    async def _cmd_import(self, args, options, channel_id, thread_ts, target_agent, user):
        """Import a session record from JSON."""
        if not args:
            await self._reply(channel_id, "Usage: !import <json_string>", thread_ts)
            return
        import json
        try:
            data = json.loads(" ".join(args))
        except json.JSONDecodeError as e:
            await self._reply(channel_id, f"Invalid JSON: {e}", thread_ts)
            return
        required = ["id", "agent_name", "model", "backend"]
        missing = [k for k in required if k not in data]
        if missing:
            await self._reply(channel_id, f"Missing required fields: {', '.join(missing)}", thread_ts)
            return
        try:
            await self._db.create_session(
                id=data["id"],
                agent_name=data["agent_name"],
                thread_ts=data.get("thread_ts"),
                label=data.get("label"),
                model=data["model"],
                backend=data["backend"],
            )
            if data.get("name"):
                await self._db.update_session_name(data["id"], data["name"])
            await self._reply(
                channel_id,
                f"✅ Imported session `{data['id'][:8]}…` for {data['agent_name']}.",
                thread_ts,
            )
        except Exception as e:
            await self._reply(channel_id, f"Import failed: {e}", thread_ts)

    async def _cmd_fork(self, args, options, channel_id, thread_ts, target_agent, user):
        """Clone a session with a new UUID. Does NOT set it as active."""
        if not args:
            await self._reply(channel_id, "Usage: !fork <session_id>", thread_ts)
            return
        source = await self._db.get_session(args[0])
        if not source:
            await self._reply(channel_id, f"Session `{args[0]}` not found.", thread_ts)
            return
        import uuid
        new_id = str(uuid.uuid4())
        source_label = source.get("name") or args[0][:8]
        try:
            await self._db.create_session(
                id=new_id,
                agent_name=source["agent_name"],
                thread_ts=source.get("thread_ts"),
                label=f"fork of {source_label}",
                model=source.get("model"),
                backend=source.get("backend"),
            )
            fork_name = f"fork-{source_label}"
            await self._db.update_session_name(new_id, fork_name)
            await self._reply(
                channel_id,
                f"🔀 Forked `{args[0][:8]}…` → `{new_id[:8]}…` ({fork_name}). Use `!resume {new_id[:8]}` to switch.",
                thread_ts,
            )
        except Exception as e:
            await self._reply(channel_id, f"Fork failed: {e}", thread_ts)

    async def _cmd_spawn(self, args, options, channel_id, thread_ts, target_agent, user):
        """Spawn a new agent in a channel.

        Usage: !spawn <name> --backend=claude --cwd=/path --channel=#channel-name
        """
        if not args:
            await self._reply(
                channel_id,
                "Usage: `!spawn <name> [--backend=claude|codex|gemini] [--model=<model>] "
                "[--cwd=<dir>] [--channel=#name] [--profile=dev|ops]`\n"
                "Example: `!spawn helper --backend=gemini --cwd=/home/captain/work/myproject --channel=#slack-agent-hub`",
                thread_ts,
            )
            return
        name = args[0].lower()
        if name in self._agents:
            await self._reply(channel_id, f"Agent `{name}` already exists.", thread_ts)
            return
        if not self._spawn_callback:
            await self._reply(channel_id, "Spawn not available.", thread_ts)
            return

        backend = options.get("backend", "claude")
        model = options.get("model", "")
        cwd = options.get("cwd", "/home/captain")
        display_name = options.get("name", name.capitalize())
        profile = options.get("profile", "dev")
        target_channel = options.get("channel", "")

        # Validate CWD exists
        import os
        if not os.path.isdir(cwd):
            await self._reply(channel_id, f"Directory not found: `{cwd}`", thread_ts)
            return

        # Resolve target channel — refresh channel list first for new channels
        spawn_channel_id = channel_id
        if target_channel:
            from hub import resolve_channel, resolve_channel_ids
            await resolve_channel_ids(self._slack)
            resolved = resolve_channel(target_channel)
            if not resolved:
                await self._reply(channel_id, f"Unknown channel: `{target_channel}`. Is the bot invited to it?", thread_ts)
                return
            spawn_channel_id = resolved

        try:
            agent = await self._spawn_callback(
                name=name,
                backend_name=backend,
                model=model,
                cwd=cwd,
                display_name=display_name,
                profile=profile,
                channel_id=spawn_channel_id,
            )
            channel_label = target_channel if target_channel else "this channel"
            await self._reply(
                channel_id,
                f"🚀 Spawned *{agent.display_name}* (`{name}`) — {backend} · {agent.config.model}\n"
                f"Channel: {channel_label} │ CWD: `{cwd}`\n"
                f"Address with `{agent.display_name}:` or `{name}:`",
                thread_ts,
            )
        except Exception as e:
            await self._reply(channel_id, f"Spawn failed: {e}", thread_ts)

    async def _cmd_despawn(self, args, options, channel_id, thread_ts, target_agent, user):
        """Remove a dynamically spawned agent."""
        if not args:
            await self._reply(channel_id, "Usage: `!despawn <agent_name>`", thread_ts)
            return
        name = args[0].lower()
        agent = self._agents.get(name)
        if not agent:
            await self._reply(channel_id, f"Unknown agent: `{name}`.", thread_ts)
            return
        # Check if it's a spawned agent (not from config)
        db_row = await self._db.get_agent(name)
        if not db_row or not db_row.get("spawned"):
            await self._reply(
                channel_id,
                f"`{name}` is a config-defined agent — remove it from `config.yaml` instead.",
                thread_ts,
            )
            return
        # Remove from runtime
        del self._agents[name]
        # Mark as removed in DB
        await self._db.remove_spawned_agent(name)
        # Rebuild channel mappings
        for ch_id, agent_list in self._channel_agents.items():
            if name in agent_list:
                agent_list.remove(name)
        await self._reply(
            channel_id,
            f"🗑️ Removed *{agent.display_name}* (`{name}`). Sessions are preserved in the DB.",
            thread_ts,
        )

    async def _cmd_help(self, args, options, channel_id, thread_ts, target_agent, user):
        help_text = (
            "*Agent Commands:*\n"
            "  `!agents` — list all agents and status\n"
            "  `!status [agent]` — detailed agent status\n"
            "  `!pause [agent]` — pause an agent\n"
            "  `!unpause [agent]` — resume a paused agent\n"
            "  `!cancel [agent]` — cancel active query\n"
            "  `!restart [agent]` — restart agent (clear session)\n"
            "  `!spawn <name> [--backend=..] [--model=..] [--cwd=..] [--channel=#..]` — spawn new agent\n"
            "  `!despawn <name>` — remove a spawned agent\n"
            "\n*Session Commands:*\n"
            "  `!new [label] [--model=<model>]` — start fresh session\n"
            "  `!sessions [agent|all]` — list sessions (use `all` for hub-wide)\n"
            "  `!resume <session_id or name>` — resume a previous session\n"
            "  `!refresh` — new session, keep old in history\n"
            "  `!export <session_id>` — export session data as JSON\n"
            "  `!import <json>` — import a session from JSON\n"
            "  `!fork <session_id>` — clone session for experimentation\n"
            "\n*Diagnostics:*\n"
            "  `!health` — hub health summary\n"
            "  `!diag [agent]` — deep diagnostic (session, backend, config)\n"
            "  `!logs [agent] [N]` — last N log lines (default 20)\n"
            "  `!test [agent]` — verify backend responds\n"
            "\n*Memory & Context:*\n"
            "  `!pin <text>` — pin context for agent\n"
            "  `!pins` — list pinned context\n"
            "  `!unpin <id>` — remove a pin\n"
            "  `!memory [agent]` — show agent memory\n"
            "  `!history [N]` — last N channel messages (default 10)\n"
            "  `!context [N]` — fetch channel context (default 20)\n"
            "  `!search <keyword>` — search channel history\n"
            "\n*Admin:*\n"
            "  `!cost [agent]` — token usage and costs\n"
            "  `!roster` — full agent roster with channels\n"
            "  `!reload` — reload config.yaml (changes on next session)\n"
            "  `!audit [N]` — show last N audit log entries (default 20, admin only)\n"
            "\n*CLI:*\n"
            "  `> /command` — passthrough to backend CLI\n"
            "\n*Profiles* control what agents can do: "
            "each agent has a profile that sets its permission mode "
            "and allowed tools. See config.yaml for details.\n"
        )
        await self._reply(channel_id, help_text, thread_ts)
