"""Live command tests — simulates Slack events against the running hub's internals.

This tests the full path: message → router → command_handler → response,
using real config and database but mocking only the Slack API layer.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from core.config import load_config
from core.router import Router, RouteAction
from core.command_handler import CommandHandler
from core.commands import parse_message
from storage.db import Database
import re


async def run_tests():
    # Load real config
    config = load_config(Path("config.yaml"))

    # Init real database
    db = Database("hub.db")
    await db.initialize()

    # Build agent mocks from config
    agents = {}
    for name, agent_cfg in config.agents.items():
        agent = MagicMock()
        agent.name = name
        agent.host_id = config.host_id
        agent.status = "active"
        agent.display_name = f"{agent_cfg.display_name or name.capitalize()}@{config.host_id}"
        agent.current_session_id = None
        agent.config = agent_cfg
        agent.backend = MagicMock()
        agent.backend.name = "claude"
        agent.backend.terminal_resume_command.return_value = None
        agent.profile = MagicMock()
        agent.profile.allowed_tools = []
        agent._active_query_task = None
        agents[name] = agent

    # Check for existing sessions
    for name, agent in agents.items():
        sessions = await db.list_sessions(name)
        if sessions:
            active = [s for s in sessions if s.get("status") == "active"]
            if active:
                agent.current_session_id = active[0]["id"]
                agent.backend.terminal_resume_command.return_value = f"claude --resume {active[0]['id']}"

    # Mock poster that captures responses
    poster = AsyncMock()
    poster.post.return_value = {"ts": "9999.9999"}
    poster.update.return_value = {"ts": "9999.9999"}

    # Mock Slack client
    slack = AsyncMock()
    slack.conversations_history.return_value = {
        "messages": [
            {"user": "U_TEST", "text": "Hello world", "ts": "1234567890.0"},
            {"user": "U_TEST", "text": "!help", "ts": "1234567891.0"},
        ]
    }

    handler = CommandHandler(agents=agents, db=db, slack_client=slack, poster=poster)

    # Build router
    channel_agents = {}
    for aname, acfg in config.agents.items():
        for ch in acfg.channels:
            channel_agents.setdefault(ch, []).append(aname)
    agent_hosts = {name: config.host_id for name in agents}
    local_agents = set(agents.keys())

    router = Router(
        ops_channel_id="C_OPS",
        channel_agents=channel_agents,
        agent_hosts=agent_hosts,
        local_agents=local_agents,
        local_host_id=config.host_id,
    )

    # ── Test all commands ──
    test_channel = list(channel_agents.keys())[0] if channel_agents else "C_TEST"
    default_agent = channel_agents.get(test_channel, ["unknown"])[0]

    commands = [
        ("!help", "should show help"),
        ("!agents", "should list agents"),
        ("!status", "should show status"),
        ("!roster", "should show roster"),
        ("!cost", "should show cost"),
        ("!search hello", "should search"),
        ("!cancel", "should handle no active query"),
        ("!pause", "should pause"),
        ("!unpause", "should unpause"),
        ("!pin Remember to be concise", "should pin"),
        ("!pins", "should list pins"),
        ("!memory", "should show memory"),
        ("!context", "should show context"),
        ("!history", "should show history"),
        ("!sessions", "should list sessions"),
    ]

    all_pass = True
    for text, desc in commands:
        poster.reset_mock()

        # Test routing
        stripped = re.sub(r"<@U[A-Z0-9]+>\s*", "", text).strip()
        parsed = parse_message(stripped)
        route_result = router.route(stripped, test_channel, "U_TEST")

        if route_result.action != RouteAction.COMMAND:
            print(f"  ROUTE FAIL: '{text}' -> {route_result.action} (expected COMMAND)")
            all_pass = False
            continue

        # Test handler
        try:
            await handler.handle(
                parsed.command, parsed.args, parsed.options,
                test_channel, None, default_agent, "U_TEST",
            )
            calls = poster.post.call_args_list
            if not calls:
                print(f"  FAIL: '{text}' — no response ({desc})")
                all_pass = False
            else:
                response_text = calls[0].kwargs.get("text", "?")[:100].replace("\n", " ")
                agent_name = calls[0].kwargs.get("agent_name", "none")
                print(f"  OK: '{text}' -> [{agent_name}] \"{response_text}\"")
        except Exception as e:
            print(f"  ERROR: '{text}' -> {type(e).__name__}: {e}")
            all_pass = False

    # Cleanup pin
    poster.reset_mock()
    await handler.handle("unpin", ["1"], {}, test_channel, None, default_agent, "U_TEST")
    calls = poster.post.call_args_list
    if calls:
        text_resp = calls[0].kwargs.get("text", "?")[:60]
        print(f"  OK: '!unpin 1' -> \"{text_resp}\"")

    # Test mention stripping (simulating what hub.py does)
    print("\n--- Mention Stripping ---")
    mention_tests = [
        ("<@U0AGE1EMBR9> !roster", "roster"),
        ("<@U0AGE1EMBR9> !help", "help"),
        ("<@U0AGE1EMBR9> !search test", "search"),
        ("<@U0AGE1EMBR9>!help", "help"),  # no space after mention
    ]
    for raw, expected_cmd in mention_tests:
        stripped = re.sub(r"<@U[A-Z0-9]+>\s*", "", raw).strip()
        parsed = parse_message(stripped)
        if parsed.command == expected_cmd:
            print(f"  OK: '{raw}' -> command='{parsed.command}'")
        else:
            print(f"  FAIL: '{raw}' -> stripped='{stripped}' command='{parsed.command}' (expected '{expected_cmd}')")
            all_pass = False

    # Test event dedup
    print("\n--- Event Dedup ---")
    seen = set()
    events = [("e1", True), ("e2", True), ("e1", False), ("e3", True), ("e2", False)]
    for eid, should_process in events:
        processed = eid not in seen
        if processed:
            seen.add(eid)
        if processed == should_process:
            print(f"  OK: event {eid} -> {'process' if processed else 'dedup'}")
        else:
            print(f"  FAIL: event {eid} -> {'process' if processed else 'dedup'} (expected {'process' if should_process else 'dedup'})")
            all_pass = False

    await db.close()
    return all_pass


if __name__ == "__main__":
    print("=" * 60)
    print("Live Command Tests (real config + real DB)")
    print("=" * 60)
    result = asyncio.run(run_tests())
    print("\n" + "=" * 60)
    print("ALL LIVE TESTS PASSED" if result else "SOME LIVE TESTS FAILED")
    print("=" * 60)
    sys.exit(0 if result else 1)
