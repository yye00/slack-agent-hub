#!/usr/bin/env python3
"""slack-agent-hub — Federated Slack-to-CLI-agent bridge."""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

import asyncio
import logging
import signal
import sys

from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from core.agent import Agent
from core.command_handler import CommandHandler
from core.commands import MessageType
from core.config import load_config
from core.heartbeat import TipRotator
from core.query import QueryEngine
from core.router import Router, RouteAction
from backends.claude import ClaudeBackend
from features.memory import read_memory, truncate_to_token_limit
from features.transcript import fetch_transcript, summarize_for_onboarding
from features.files import download_slack_files, build_file_annotation, extract_file_paths
from features.permalinks import expand_permalinks
from slack_io.messages import chunk_response
from slack_io.posting import SlackPoster
from storage.db import Database

# ── Logging ──

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Globals ──

config = None
db: Database = None
app: AsyncApp = None
poster: SlackPoster = None
agents: dict[str, Agent] = {}
router: Router = None
command_handler: CommandHandler = None
channel_id_map: dict[str, str] = {}  # "#name" -> "C123..."
_shutting_down = False

# ── Backend registry ──

BACKEND_CLASSES = {
    "claude": ClaudeBackend,
    # "codex": CodexBackend,   # deferred
    # "gemini": GeminiBackend, # deferred
}


async def resolve_channel_ids(slack_client):
    """Resolve #channel-name references to Slack channel IDs."""
    global channel_id_map
    try:
        resp = await slack_client.conversations_list(types="public_channel,private_channel", limit=1000)
        for ch in resp.get("channels", []):
            channel_id_map[f"#{ch['name']}"] = ch["id"]
            channel_id_map[ch["id"]] = ch["id"]  # passthrough for raw IDs
    except Exception as e:
        logger.error(f"Failed to list channels: {e}")


def resolve_channel(ref: str) -> str | None:
    """Resolve a channel reference to its ID."""
    return channel_id_map.get(ref) or channel_id_map.get(f"#{ref}")


async def initialize_agents():
    """Create Agent instances from config."""
    global agents, router

    for name, agent_cfg in config.agents.items():
        backend_name = agent_cfg.backend
        backend_cls = BACKEND_CLASSES.get(backend_name)
        if not backend_cls:
            logger.warning(f"Backend '{backend_name}' not implemented, skipping agent '{name}'")
            continue

        backend = backend_cls()
        profile = config.profiles[agent_cfg.profile]

        agent = Agent(
            name=name,
            host_id=config.host_id,
            config=agent_cfg,
            profile=profile,
            backend=backend,
            db=db,
        )
        agents[name] = agent

        # Resume a previous session if configured
        if agent_cfg.resume_session:
            agent.current_session_id = agent_cfg.resume_session
            await agent.backend.start_session(
                cwd=agent_cfg.cwd,
                system_prompt="",  # will be rebuilt on first query
                model=agent_cfg.model,
            )
            logger.info(f"Resuming session {agent_cfg.resume_session[:8]}… for {agent.display_name}")

        await db.upsert_agent(name, "active", agent._started_at if hasattr(agent, '_started_at') else "")

        logger.info(f"Initialized agent: {agent.display_name} ({backend_name})")

    # Build router
    channel_agents: dict[str, list[str]] = {}
    agent_hosts: dict[str, str] = {}
    local_agents: set[str] = set()

    for name, agent in agents.items():
        agent_hosts[name] = config.host_id
        local_agents.add(name)
        for ch_ref in agent.config.channels:
            ch_id = resolve_channel(ch_ref)
            if ch_id:
                channel_agents.setdefault(ch_id, []).append(name)

    ops_id = resolve_channel(config.ops_channel) or ""
    router = Router(
        ops_channel_id=ops_id,
        channel_agents=channel_agents,
        agent_hosts=agent_hosts,
        local_agents=local_agents,
    )

    global command_handler
    command_handler = CommandHandler(agents=agents, db=db, slack_client=app.client, poster=poster)


async def handle_message(event, say):
    """Main message handler — routes to agents or commands."""
    if _shutting_down:
        return

    text = event.get("text", "")
    channel_id = event.get("channel", "")
    user = event.get("user", "")
    thread_ts = event.get("thread_ts")

    if not text or not user:
        return

    # Ignore bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    result = router.route(text, channel_id, user)

    if result.action == RouteAction.IGNORE:
        return

    if result.action == RouteAction.COMMAND:
        await command_handler.handle(
            result.parsed.command, result.parsed.args, result.parsed.options,
            channel_id, thread_ts, result.target_agent, user,
        )
        return

    if result.action == RouteAction.AGENT_QUERY:
        agent = agents.get(result.target_agent)
        if agent and agent.status == "active":
            await run_agent_query(agent, text, channel_id, thread_ts)
        return

    if result.action == RouteAction.CLI_PASSTHROUGH:
        agent = agents.get(result.target_agent)
        if agent:
            response = await agent.backend.cli_passthrough(
                agent.current_session_id or "", result.parsed.cli_command
            )
            formatted = (
                f"```\n{agent.display_name} ({agent.backend.name}) $ {result.parsed.cli_command}\n"
                f"{response}\n```"
            )
            await poster.post(
                channel=channel_id, text=formatted, thread_ts=thread_ts,
                agent_name=agent.name,
            )
        return

    if result.action == RouteAction.BROADCAST:
        for agent_name in result.broadcast_agents:
            agent = agents.get(agent_name)
            if agent and agent.status == "active":
                await run_agent_query(agent, result.parsed.text, channel_id, thread_ts)
        return


async def run_agent_query(agent, text, channel_id, thread_ts):
    """Execute a query against an agent."""
    # Expand permalinks
    text = await expand_permalinks(app.client, text)

    # Build system prompt
    memory = read_memory(agent.config.cwd)
    memory = truncate_to_token_limit(memory)
    pins = await db.list_pins(channel_id)
    pin_texts = [p["content"] for p in pins]

    # Build roster from registry channel (populated by core/registry.py)
    roster_text = ""
    try:
        from core.registry import parse_registry_messages, build_roster_text
        registry_ch = resolve_channel(config.registry_channel)
        if registry_ch:
            resp = await app.client.conversations_history(channel=registry_ch, limit=50)
            msgs = resp.get("messages", [])
            roster = parse_registry_messages(msgs)
            roster_text = build_roster_text(roster, agent.name, config.host_id)
    except Exception as e:
        logger.debug(f"Failed to build roster: {e}")

    system_prompt = agent.build_system_prompt(
        roster_text=roster_text,
        pins=pin_texts,
        memory_text=memory,
    )

    # Start or resume session
    session_id = agent.current_session_id
    if not session_id:
        session_id = await agent.backend.start_session(
            cwd=agent.config.cwd,
            system_prompt=system_prompt,
            model=agent.config.model,
        )

    # Run query
    engine = QueryEngine(
        agent=agent,
        slack_client=app.client,
        poster=poster,
        db=db,
        heartbeat_interval=config.heartbeat.interval_secs,
        stall_warn_mins=config.heartbeat.stall_warn_mins,
        tips_enabled=config.heartbeat.tips,
    )

    result = await engine.execute(
        prompt=text,
        channel_id=channel_id,
        thread_ts=thread_ts,
        session_id=session_id,
    )

    # Update session tracking
    if result.session_id:
        agent.current_session_id = result.session_id

    # Auto-upload referenced files
    if result.success and result.text:
        paths = extract_file_paths(result.text)
        for p in paths[:5]:  # max 5 auto-uploads
            try:
                await app.client.files_upload_v2(
                    channel=channel_id,
                    file=p,
                    thread_ts=thread_ts,
                )
            except Exception as e:
                logger.debug(f"Auto-upload failed for {p}: {e}")


async def announce_agents():
    """Post an introduction message in each agent's channels on startup."""
    for name, agent in agents.items():
        label = agent.config.display_name or name.capitalize()
        profile_name = agent.config.profile
        profile = config.profiles.get(profile_name)
        tools_list = ", ".join(profile.allowed_tools) if profile else "N/A"
        lines = [
            f"👋 *{label}@{config.host_id}* online",
            f"• *Addressable as:* `@{name}` or `@{name}@{config.host_id}`",
            f"• *Backend:* {agent.backend.name} ({agent.config.model})",
            f"• *Working directory:* `{agent.config.cwd}`",
            f"• *Profile:* {profile_name} — permission mode: {profile.permission_mode if profile else 'N/A'}",
            f"• *Allowed tools:* {tools_list}",
            f"• *Launch command:* `uv run python hub.py` (config: `config.yaml`)",
            f"• *Host:* {config.host_id}",
            "",
            "Type `!help` for available commands.",
        ]
        msg = "\n".join(lines)

        for ch_ref in agent.config.channels:
            ch_id = resolve_channel(ch_ref)
            if ch_id:
                try:
                    await poster.post(channel=ch_id, text=msg, agent_name=name)
                except Exception as e:
                    logger.warning(f"Failed to announce {name} in {ch_ref}: {e}")


async def shutdown(sig_name: str):
    """Graceful shutdown."""
    global _shutting_down
    _shutting_down = True
    logger.info(f"Shutting down on {sig_name}...")

    # Cancel active queries
    for agent in agents.values():
        if agent._active_query_task and not agent._active_query_task.done():
            agent._active_query_task.cancel()

    await db.close()
    logger.info("Shutdown complete.")


async def main():
    """Main entry point."""
    global config, db, app, poster

    config_path = Path(os.getenv("CONFIG_PATH", "config.yaml"))
    config = load_config(config_path)

    db_path = Path(os.getenv("DB_PATH", "hub.db"))
    db = Database(db_path)
    await db.initialize()

    app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
    app.event("message")(handle_message)

    poster = SlackPoster(
        client=app.client,
        host_id=config.host_id,
        host_color=config.host_color,
    )

    await resolve_channel_ids(app.client)
    await initialize_agents()
    await announce_agents()

    logger.info(f"Hub {config.host_id} starting with {len(agents)} agent(s)")

    # Signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s.name)))

    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
