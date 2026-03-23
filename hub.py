#!/usr/bin/env python3
"""slack-agent-hub — Federated Slack-to-CLI-agent bridge."""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

import asyncio
import logging
import re
import signal
import sys

from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from core.agent import Agent
from core.lifecycle import LifecycleNotifier, SessionEvent
from core.command_handler import CommandHandler
from core.health import HealthMonitor
from core.commands import MessageType
from core.config import load_config, AgentConfig
from core.rate_limit import RateLimiter
from core.heartbeat import TipRotator
from core.query import QueryEngine
from core.router import Router, RouteAction
from core.permissions import PermissionChecker
from core.selftest import StartupSelfTest
from core.thread_dispatch import is_thread_reply, build_background_prompt
from backends.claude import ClaudeBackend
from backends.gemini import GeminiBackend
from backends.codex import CodexBackend
from core.session_naming import generate_session_name
from core.continuity import build_resume_preamble, generate_session_summary
from features.memory import read_memory, truncate_to_token_limit, append_memory
from features.transcript import fetch_transcript, summarize_for_onboarding
from features.files import download_slack_files, build_file_annotation, extract_file_paths
from features.permalinks import expand_permalinks
from slack_io.messages import chunk_response
from slack_io.posting import SlackPoster
from storage.db import Database
from core.structured_logging import setup_logging

# ── Logging ──

os.makedirs("logs", exist_ok=True)
json_logs = os.getenv("JSON_LOGS", "").lower() in ("1", "true", "yes")
setup_logging(
    log_dir="logs",
    json_stdout=json_logs,
    level=os.getenv("LOG_LEVEL", "INFO"),
)
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
permission_checker: PermissionChecker | None = None
rate_limiter: RateLimiter | None = None
lifecycle: LifecycleNotifier | None = None
health_monitor: HealthMonitor | None = None
_shutting_down = False
_selftest_passed = False
_socket_handler = None

# ── Backend registry ──

BACKEND_CLASSES = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
    "gemini": GeminiBackend,
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


async def spawn_agent(
    name: str,
    backend_name: str,
    model: str,
    cwd: str,
    display_name: str,
    profile: str,
    channel_id: str,
) -> Agent:
    """Dynamically spawn a new agent and register it in the channel."""
    global router

    # Reserve the Slack app name — using it as an agent display name is confusing
    app_name = os.getenv("SLACK_APP_NAME", "Skippy").lower()
    if display_name.lower() == app_name or name.lower() == app_name:
        raise ValueError(
            f"'{display_name or name}' is reserved (it's the Slack app name). Choose a different name."
        )

    backend_cls = BACKEND_CLASSES.get(backend_name)
    if not backend_cls:
        raise ValueError(f"Unknown backend: {backend_name}. Available: {', '.join(BACKEND_CLASSES)}")

    # Use backend default model if none specified
    if not model:
        backend_cfg = config.backends.get(backend_name)
        model = backend_cfg.get("default_model", "") if backend_cfg else ""

    profile_cfg = config.profiles.get(profile)
    if not profile_cfg:
        raise ValueError(f"Unknown profile: {profile}. Available: {', '.join(config.profiles)}")

    backend = backend_cls()
    agent_cfg = AgentConfig(
        backend=backend_name,
        model=model,
        channels=[channel_id],
        cwd=cwd,
        profile=profile,
        display_name=display_name,
    )

    agent = Agent(
        name=name,
        host_id=config.host_id,
        config=agent_cfg,
        profile=profile_cfg,
        backend=backend,
        db=db,
    )
    agents[name] = agent

    # Persist spawned agent config to DB so it survives restarts
    import json
    config_data = {
        "backend": backend_name, "model": model,
        "channels": [channel_id], "cwd": cwd,
        "profile": profile, "display_name": display_name,
    }
    await db.save_spawned_agent(name, json.dumps(config_data), "active", agent._started_at)

    # Register in channel_agents and rebuild router
    channel_agents = {}
    agent_hosts = {}
    local_agents = set()
    display_names = {}

    for n, a in agents.items():
        agent_hosts[n] = config.host_id
        local_agents.add(n)
        display_names[n] = a.display_name
        for ch_ref in a.config.channels:
            ch_id = resolve_channel(ch_ref) or ch_ref
            channel_agents.setdefault(ch_id, []).append(n)

    ops_id = resolve_channel(config.ops_channel) or ""
    router = Router(
        ops_channel_id=ops_id,
        channel_agents=channel_agents,
        agent_hosts=agent_hosts,
        local_agents=local_agents,
        local_host_id=config.host_id,
        display_names=display_names,
    )

    # Update command handler mappings
    command_handler._channel_agents = channel_agents
    command_handler._agents = agents

    # Register display name and color with poster
    poster.set_agent_display_name(name, agent.display_name)

    logger.info(f"Spawned agent: {agent.display_name} ({backend_name}) in channel {channel_id}")
    return agent


async def initialize_agents():
    """Create Agent instances from config and restore spawned agents from DB."""
    global agents, router
    import json as _json

    # ── Phase 1: load agents defined in config.yaml ──
    for name, agent_cfg in config.agents.items():
        backend_name = agent_cfg.backend
        backend_cls = BACKEND_CLASSES.get(backend_name)
        if not backend_cls:
            logger.warning(f"Backend '{backend_name}' not implemented, skipping agent '{name}'")
            continue

        backend = backend_cls()
        profile = config.profiles[agent_cfg.profile]

        # Set permission mode from profile on the backend
        if hasattr(backend, '_permission_mode'):
            backend._permission_mode = profile.permission_mode

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

    # ── Phase 2: restore dynamically spawned agents from DB ──
    spawned_rows = await db.list_spawned_agents()
    for row in spawned_rows:
        name = row["name"]
        if name in agents:
            continue  # Config agent takes precedence over DB

        cfg_raw = row.get("config_json")
        if not cfg_raw:
            logger.warning(f"Spawned agent '{name}' has no config_json, skipping")
            continue

        try:
            cfg = _json.loads(cfg_raw)
        except _json.JSONDecodeError:
            logger.warning(f"Spawned agent '{name}' has invalid config_json, skipping")
            continue

        backend_name = cfg.get("backend", "")
        backend_cls = BACKEND_CLASSES.get(backend_name)
        if not backend_cls:
            logger.warning(f"Spawned agent '{name}' uses unknown backend '{backend_name}', skipping")
            continue

        profile_name = cfg.get("profile", "dev")
        profile_cfg = config.profiles.get(profile_name)
        if not profile_cfg:
            logger.warning(f"Spawned agent '{name}' uses unknown profile '{profile_name}', skipping")
            continue

        backend = backend_cls()
        model = cfg.get("model", "")
        agent_cfg = AgentConfig(
            backend=backend_name,
            model=model,
            channels=cfg.get("channels", []),
            cwd=cfg.get("cwd", "/home/captain"),
            profile=profile_name,
            display_name=cfg.get("display_name", name.capitalize()),
        )

        agent = Agent(
            name=name,
            host_id=config.host_id,
            config=agent_cfg,
            profile=profile_cfg,
            backend=backend,
            db=db,
        )
        agents[name] = agent

        # Auto-resume the most recent session for this agent
        sessions = await db.list_sessions(name)
        if sessions:
            latest = sessions[0]  # Already sorted by created_at DESC
            agent.current_session_id = latest["id"]
            logger.info(f"Restored spawned agent: {agent.display_name} ({backend_name}), "
                        f"resuming session {latest['id'][:8]}…")
        else:
            logger.info(f"Restored spawned agent: {agent.display_name} ({backend_name}), no previous session")

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

    # Build display name mapping for routing (so "Ziggy:" routes to "debater")
    display_names: dict[str, str] = {}
    for name, agent in agents.items():
        display_names[name] = agent.display_name

    ops_id = resolve_channel(config.ops_channel) or ""
    router = Router(
        ops_channel_id=ops_id,
        channel_agents=channel_agents,
        agent_hosts=agent_hosts,
        local_agents=local_agents,
        local_host_id=config.host_id,
        display_names=display_names,
    )

    global command_handler
    command_handler = CommandHandler(
        agents=agents, db=db, slack_client=app.client, poster=poster,
        channel_agents=channel_agents, spawn_callback=spawn_agent,
    )


_seen_events: set[str] = set()
_SEEN_MAX = 500


async def handle_message(event, say):
    """Main message handler — routes to agents or commands."""
    if _shutting_down:
        return

    if not _selftest_passed:
        return

    # Deduplicate: Slack fires both 'message' and 'app_mention' for @-mentions
    event_ts = event.get("client_msg_id") or event.get("ts", "")
    if event_ts in _seen_events:
        return
    _seen_events.add(event_ts)
    if len(_seen_events) > _SEEN_MAX:
        # Prune oldest half to avoid unbounded growth
        to_remove = list(_seen_events)[:_SEEN_MAX // 2]
        for k in to_remove:
            _seen_events.discard(k)

    text = event.get("text", "")
    channel_id = event.get("channel", "")
    user = event.get("user", "")
    thread_ts = event.get("thread_ts")

    if not text or not user:
        return

    # Ignore bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Strip bot mention prefix so "@Skippy !help" parses as "!help"
    text = re.sub(r"<@U[A-Z0-9]+>\s*", "", text).strip()
    if not text:
        return

    result = router.route(text, channel_id, user)

    if result.action == RouteAction.IGNORE:
        return

    if result.action == RouteAction.COMMAND:
        cmd = result.parsed.command
        try:
            if permission_checker and not permission_checker.check_command(user, cmd):
                await poster.post(
                    channel=channel_id,
                    text=permission_checker.denial_message(user, cmd),
                    thread_ts=thread_ts,
                )
                return
            await db.log_audit(
                user_id=user,
                action="COMMAND",
                target=cmd,
                channel_id=channel_id,
                detail=text[:500],
            )
            await command_handler.handle(
                cmd, result.parsed.args, result.parsed.options,
                channel_id, thread_ts, result.target_agent, user,
            )
        except Exception as e:
            logger.exception(f"Command !{cmd} failed: {e}")
            try:
                await poster.post(
                    channel=channel_id, text=f"❌ Command error: {e}",
                    thread_ts=thread_ts,
                )
            except Exception:
                pass
        return

    if result.action == RouteAction.AGENT_QUERY:
        if rate_limiter and not rate_limiter.allow(user):
            await poster.post(
                channel=channel_id,
                text="⏱️ Rate limit reached. Try again shortly.",
                thread_ts=thread_ts,
                agent_name=result.target_agent,
            )
            return
        # Handle file attachments
        files = event.get("files", [])
        if files:
            try:
                downloaded = await download_slack_files(app.client, files, channel_id)
                if downloaded:
                    text += build_file_annotation(downloaded)
            except Exception as e:
                logger.debug(f"File download failed: {e}")
        agent = agents.get(result.target_agent)
        if agent and agent.status == "active":
            is_bg = is_thread_reply(event)
            agent._active_query_task = asyncio.create_task(
                run_agent_query(agent, text, channel_id, thread_ts, is_background=is_bg)
            )
            try:
                await agent._active_query_task
            finally:
                agent._active_query_task = None
        return

    if result.action == RouteAction.CLI_PASSTHROUGH:
        if permission_checker and not permission_checker.check_cli_passthrough(user):
            await poster.post(
                channel=channel_id,
                text=permission_checker.cli_denial_message(user),
                thread_ts=thread_ts,
            )
            return
        agent = agents.get(result.target_agent)
        if agent:
            await db.log_audit(
                user_id=user,
                action="CLI_PASSTHROUGH",
                target=result.target_agent,
                channel_id=channel_id,
                detail=result.parsed.cli_command[:500],
            )
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
        tasks = []
        for agent_name in result.broadcast_agents:
            agent = agents.get(agent_name)
            if agent and agent.status == "active":
                tasks.append(
                    run_agent_query(agent, result.parsed.text, channel_id, thread_ts)
                )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return

    if result.action == RouteAction.DISCUSS:
        rounds = int(result.parsed.options.get("rounds", 2))
        rounds = max(1, min(rounds, 5))  # clamp to 1-5
        asyncio.create_task(
            run_discussion(
                topic=result.parsed.text,
                agent_names=result.broadcast_agents,
                channel_id=channel_id,
                thread_ts=thread_ts,
                rounds=rounds,
            )
        )
        return


async def run_agent_query(agent, text, channel_id, thread_ts, is_background=False):
    """Execute a query against an agent."""
    try:
        await _run_agent_query_inner(agent, text, channel_id, thread_ts, is_background)
    except asyncio.CancelledError:
        raise  # Let cancellation propagate
    except Exception as e:
        logger.exception(f"run_agent_query failed: {e}")
        try:
            await poster.post(
                channel=channel_id,
                text=f"❌ Internal error: {e}",
                thread_ts=thread_ts,
                agent_name=agent.name,
            )
        except Exception:
            pass


async def _run_agent_query_inner(agent, text, channel_id, thread_ts, is_background=False):
    """Inner query logic — wrapped by run_agent_query for safety."""
    if is_background and agent.current_session_id:
        text = build_background_prompt(text, agent.backend.name)

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
        # Check for previous session summary to inject as preamble
        prev = await db.get_previous_session(agent.name)
        if prev and prev.get("summary"):
            preamble = build_resume_preamble(
                previous_session_name=prev.get("name") or prev["id"][:8],
                summary=prev["summary"],
                ended_cleanly=bool(prev.get("ended_cleanly", True)),
            )
            system_prompt = preamble + "\n\n" + system_prompt

        session_id = await agent.backend.start_session(
            cwd=agent.config.cwd,
            system_prompt=system_prompt,
            model=agent.config.model,
        )
        if session_id and lifecycle:
            await lifecycle.notify(SessionEvent(
                type="start",
                agent_name=agent.name,
                agent_display=agent.display_name,
                session_id=session_id,
                channel_id=channel_id,
            ))

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

    # Check for handoff pattern in agent's response
    if result.success and result.text:
        from features.handoff import detect_handoff_in_response
        handoff = detect_handoff_in_response(result.text)
        if handoff:
            # Resolve target by internal name or display name
            target_name = handoff.target_agent  # already lowercased
            target = agents.get(target_name)
            if not target:
                # Try display name lookup
                for a in agents.values():
                    if a.display_name.lower() == target_name or a.name.lower() == target_name:
                        target = a
                        break
            if target and target.status == "active" and target.name != agent.name:
                logger.info(f"Handoff: {agent.name} → {target.name}: {handoff.content[:80]}")
                await poster.post_plain(
                    channel=channel_id,
                    text=f"↪ _{agent.display_name}_ → _{target.display_name}_",
                    thread_ts=thread_ts,
                )
                asyncio.create_task(
                    run_agent_query(target, handoff.content, channel_id, thread_ts)
                )

    # Update session tracking — detect restarts (skip if initial session creation)
    if result.session_id and session_id and result.session_id != session_id:
        # Save summary for the old session before marking it rotated
        if session_id:
            try:
                summary = generate_session_summary(result.text or "")
                await db.save_session_summary(session_id, summary, ended_cleanly=True)
            except Exception as e:
                logger.debug(f"Failed to save session summary: {e}")
        if lifecycle:
            await lifecycle.notify(SessionEvent(
                type="restart",
                agent_name=agent.name,
                agent_display=agent.display_name,
                session_id=result.session_id,
                channel_id=channel_id,
                previous_session_id=session_id,
                reason="session rotated by backend",
            ))
    if result.session_id:
        agent.current_session_id = result.session_id

    # Persist session record and generate name on first query
    if result.session_id:
        existing = await db.get_session(result.session_id)
        if not existing:
            session_name = generate_session_name(text)
            await db.create_session(
                id=result.session_id,
                agent_name=agent.name,
                thread_ts=thread_ts,
                label=None,
                model=agent.config.model,
                backend=agent.backend.name,
            )
            await db.update_session_name(result.session_id, session_name)

    # Auto-save session summary to agent MEMORY.md
    if result.success and result.text:
        try:
            summary = generate_session_summary(result.text, max_length=300)
            if summary:
                session_name = None
                if result.session_id:
                    session_rec = await db.get_session(result.session_id)
                    session_name = session_rec.get("name") if session_rec else None
                header = f"## Session: {session_name or 'unnamed'}"
                append_memory(agent.config.cwd, f"\n{header}\n{summary}\n")
        except Exception as e:
            logger.debug(f"Auto-save to memory failed: {e}")

    # Auto-upload referenced files
    if result.success and result.text:
        paths = list(dict.fromkeys(extract_file_paths(result.text)))  # deduplicate
        logger.info(f"Auto-upload: found {len(paths)} file paths in response")
        for p in paths[:5]:  # max 5 auto-uploads
            try:
                logger.info(f"Auto-uploading {p} to {channel_id}")
                await app.client.files_upload_v2(
                    channel=channel_id,
                    file=p,
                    thread_ts=thread_ts,
                )
                logger.info(f"Auto-uploaded {p}")
            except Exception as e:
                logger.warning(f"Auto-upload failed for {p}: {e}")


async def run_discussion(topic, agent_names, channel_id, thread_ts, rounds=2):
    """Orchestrate a multi-round discussion between agents.

    Round 1: All agents respond to the topic concurrently.
    Round 2+: Each agent sees what others said and responds sequentially.
    """
    active_agents = []
    for name in agent_names:
        agent = agents.get(name)
        if agent and agent.status == "active":
            active_agents.append(agent)

    if len(active_agents) < 2:
        await poster.post(
            channel=channel_id,
            text="Need at least 2 active agents for a discussion.",
            thread_ts=thread_ts,
        )
        return

    names_str = ", ".join(f"*{a.display_name}*" for a in active_agents)
    await poster.post_plain(
        channel=channel_id,
        text=f"💬 *Discussion starting* — {names_str} │ {rounds} round{'s' if rounds != 1 else ''}\n> _{topic}_",
        thread_ts=thread_ts,
    )

    # Track responses per round: {agent_name: response_text}
    responses: dict[str, str] = {}

    for round_num in range(1, rounds + 1):
        if round_num == 1:
            # Round 1: all agents respond concurrently to the raw topic
            prompt = topic
            tasks = []
            for agent in active_agents:
                tasks.append(
                    _discussion_query(agent, prompt, channel_id, thread_ts)
                )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for agent, result in zip(active_agents, results):
                if isinstance(result, Exception):
                    logger.warning(f"Discussion round 1 failed for {agent.name}: {result}")
                    responses[agent.name] = "(no response)"
                elif result:
                    responses[agent.name] = result
                else:
                    responses[agent.name] = "(no response)"
        else:
            # Round 2+: sequential — each agent sees what others said
            await poster.post_plain(
                channel=channel_id,
                text=f"━━━  *Round {round_num}*  ━━━",
                thread_ts=thread_ts,
            )
            new_responses: dict[str, str] = {}
            for agent in active_agents:
                # Build context from other agents' responses
                others = []
                for other in active_agents:
                    if other.name != agent.name and responses.get(other.name):
                        text_snippet = responses[other.name][:1500]
                        others.append(f"**{other.display_name}** said:\n{text_snippet}")

                follow_up = (
                    f"This is a group discussion about: {topic}\n\n"
                    f"Here's what the other participants said:\n\n"
                    + "\n\n---\n\n".join(others)
                    + "\n\nNow respond with your perspective. "
                    "You can agree, disagree, build on their points, or raise new angles. "
                    "Be direct and concise."
                )
                result = await _discussion_query(agent, follow_up, channel_id, thread_ts)
                new_responses[agent.name] = result or "(no response)"

            responses = new_responses

    await poster.post_plain(
        channel=channel_id,
        text=f"💬 *Discussion complete* — {rounds} round{'s' if rounds != 1 else ''} finished.",
        thread_ts=thread_ts,
    )


async def _discussion_query(agent, prompt, channel_id, thread_ts) -> str:
    """Run a single agent query for discussion and return the response text."""
    try:
        engine = QueryEngine(
            agent=agent,
            slack_client=app.client,
            poster=poster,
            db=db,
            heartbeat_interval=config.heartbeat.interval_secs,
            stall_warn_mins=config.heartbeat.stall_warn_mins,
            tips_enabled=config.heartbeat.tips,
        )

        # Start session if needed
        session_id = agent.current_session_id
        if not session_id:
            memory = read_memory(agent.config.cwd)
            memory = truncate_to_token_limit(memory)
            pins = await db.list_pins(channel_id)
            pin_texts = [p["content"] for p in pins]
            system_prompt = agent.build_system_prompt(
                roster_text="", pins=pin_texts, memory_text=memory,
            )
            session_id = await agent.backend.start_session(
                cwd=agent.config.cwd,
                system_prompt=system_prompt,
                model=agent.config.model,
            )

        result = await engine.execute(
            prompt=prompt,
            channel_id=channel_id,
            thread_ts=thread_ts,
            session_id=session_id,
        )

        if result.session_id:
            agent.current_session_id = result.session_id

        return result.text if result.success else ""
    except Exception as e:
        logger.exception(f"Discussion query failed for {agent.name}: {e}")
        return ""


async def announce_agents():
    """Post a compact introduction for each agent in their channels."""
    # Group agents by channel to post a single combined announcement
    channel_agents: dict[str, list[str]] = {}
    for name, agent in agents.items():
        for ch_ref in agent.config.channels:
            ch_id = resolve_channel(ch_ref)
            if ch_id:
                channel_agents.setdefault(ch_id, []).append(name)

    for ch_id, agent_names in channel_agents.items():
        if len(agent_names) == 1:
            # Single agent — concise announcement
            name = agent_names[0]
            agent = agents[name]
            label = agent.display_name
            msg = (
                f"👋 *{label}* online — "
                f"`{agent.backend.name}` · `{agent.config.model}` · "
                f"address as `{label}:` │ `!help` for commands"
            )
            try:
                await poster.post(channel=ch_id, text=msg, agent_name=name)
            except Exception as e:
                logger.warning(f"Failed to announce {name} in {ch_id}: {e}")
        else:
            # Multi-agent channel — combined roster
            lines = ["👋 *Agents online:*"]
            for name in agent_names:
                agent = agents[name]
                label = agent.display_name
                lines.append(
                    f"  •  *{label}* — `{agent.backend.name}` · `{agent.config.model}`"
                )
            lines.append(f"_Address by name (e.g. `Skippy:` or `debater:`), `Everyone:` to broadcast, `Debate:` for discussion_")
            try:
                await poster.post_plain(channel=ch_id, text="\n".join(lines))
            except Exception as e:
                logger.warning(f"Failed to announce agents in {ch_id}: {e}")


async def shutdown(sig_name: str):
    """Graceful shutdown."""
    global _shutting_down, _socket_handler
    _shutting_down = True
    logger.info(f"Shutting down on {sig_name}...")

    # Save session summaries before shutdown
    for agent in agents.values():
        if agent.current_session_id:
            try:
                await db.save_session_summary(
                    agent.current_session_id,
                    summary="Session ended by hub shutdown.",
                    ended_cleanly=True,
                )
            except Exception as e:
                logger.debug(f"Failed to save session summary for {agent.name}: {e}")

    if health_monitor:
        health_monitor.stop()

    # Cancel active queries
    for agent in agents.values():
        if agent._active_query_task and not agent._active_query_task.done():
            agent._active_query_task.cancel()

    # Close Socket Mode handler to unblock start_async()
    if _socket_handler:
        try:
            await _socket_handler.close_async()
        except Exception as e:
            logger.debug(f"Socket handler close error: {e}")

    await db.close()
    logger.info("Shutdown complete.")


async def main():
    """Main entry point."""
    global config, db, app, poster, permission_checker, rate_limiter

    config_path = Path(os.getenv("CONFIG_PATH", "config.yaml"))
    config = load_config(config_path)

    db_path = Path(os.getenv("DB_PATH", "hub.db"))
    db = Database(db_path)
    await db.initialize()

    permission_checker = PermissionChecker(config.permissions)
    rate_limiter = RateLimiter(
        max_tokens=config.rate_limit.max_queries_per_user,
        refill_per_sec=config.rate_limit.refill_per_sec,
    )

    app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
    app.event("message")(handle_message)
    app.event("app_mention")(handle_message)  # treat @mentions same as messages

    poster = SlackPoster(
        client=app.client,
        host_id=config.host_id,
        host_color=config.host_color,
    )

    # Register per-agent display names and colors
    auto_agents = []
    for name, agent_cfg in config.agents.items():
        display = agent_cfg.display_name or name.capitalize()
        poster.set_agent_display_name(name, display)
        if agent_cfg.color:
            poster.set_agent_color(name, agent_cfg.color)
        else:
            auto_agents.append(name)
    # Distribute auto-generated colors evenly across the hue wheel
    for i, name in enumerate(sorted(auto_agents)):
        from slack_io.posting import _hsl_to_hex
        hue = (i / max(len(auto_agents), 1) + 0.05) % 1.0  # offset to avoid pure red
        color = _hsl_to_hex(hue, 0.55, 0.50)
        poster.set_agent_color(name, color)

    await resolve_channel_ids(app.client)

    global lifecycle
    ops_id = resolve_channel(config.ops_channel) or ""
    lifecycle = LifecycleNotifier(poster=poster, ops_channel_id=ops_id)

    # Run startup self-test
    all_channel_ids = set()
    for agent_cfg in config.agents.values():
        for ch_ref in agent_cfg.channels:
            ch_id = resolve_channel(ch_ref)
            if ch_id:
                all_channel_ids.add(ch_id)

    selftest = StartupSelfTest(
        slack_client=app.client,
        poster=poster,
        ops_channel_id=ops_id,
    )
    global _selftest_passed
    _selftest_passed = await selftest.run_and_report(
        channel_ids=list(all_channel_ids),
        backend_names=list(config.backends.keys()),
    )

    if not _selftest_passed:
        logger.error("Critical self-test failures — hub will not accept messages")

    await initialize_agents()
    await announce_agents()

    global health_monitor
    health_monitor = HealthMonitor(
        agents=agents,
        poster=poster,
        ops_channel_id=ops_id,
        host_id=config.host_id,
        interval_secs=300,
    )
    health_monitor.start()

    logger.info(f"Hub {config.host_id} starting with {len(agents)} agent(s)")

    # Signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s.name)))

    global _socket_handler
    _socket_handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await _socket_handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
