"""Integration tests for command parsing, routing, and handler dispatch."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.commands import MessageType, parse_message
from core.router import RouteAction, Router
from core.command_handler import CommandHandler


# ── Command Parser Tests ──────────────────────────────────────────

def test_parse_commands():
    """All documented commands must parse as COMMAND type."""
    commands = [
        "!help", "!agents", "!status", "!roster", "!cost",
        "!search hello", "!cancel", "!pause", "!unpause",
        "!pin Always respond concisely", "!pins", "!unpin 1",
        "!memory", "!context", "!history", "!test hello",
        "!sessions", "!sessions tester",
        "!export abc123", "!import abc123", "!fork abc123",
    ]
    failures = []
    for cmd in commands:
        result = parse_message(cmd)
        if result.type != MessageType.COMMAND:
            failures.append(f"  FAIL: '{cmd}' -> {result.type} (expected COMMAND)")
        else:
            print(f"  OK: '{cmd}' -> command='{result.command}', args={result.args}")
    if failures:
        print("\nFAILURES:")
        print("\n".join(failures))
    return len(failures) == 0


def test_parse_with_mention_stripped():
    """After hub strips <@BOT_ID>, commands should still parse."""
    import re
    texts = [
        "<@U0AGE1EMBR9> !roster",
        "<@U0AGE1EMBR9> !help",
        "<@U0AGE1EMBR9> !search test",
        "<@U0AGE1EMBR9> !cancel tester",
    ]
    failures = []
    for raw in texts:
        stripped = re.sub(r"<@U[A-Z0-9]+>\s*", "", raw).strip()
        result = parse_message(stripped)
        if result.type != MessageType.COMMAND:
            failures.append(f"  FAIL: '{raw}' -> stripped='{stripped}' -> {result.type}")
        else:
            print(f"  OK: '{raw}' -> stripped='{stripped}' -> command='{result.command}'")
    if failures:
        print("\nFAILURES:")
        print("\n".join(failures))
    return len(failures) == 0


def test_parse_html_entities():
    """Slack HTML entities must be unescaped before parsing."""
    cases = [
        ("> /status", MessageType.CLI_PASSTHROUGH),
        ("&gt; /status", MessageType.CLI_PASSTHROUGH),
        ("!search foo&amp;bar", MessageType.COMMAND),
    ]
    failures = []
    for text, expected_type in cases:
        result = parse_message(text)
        if result.type != expected_type:
            failures.append(f"  FAIL: '{text}' -> {result.type} (expected {expected_type})")
        else:
            print(f"  OK: '{text}' -> {result.type}")
    if failures:
        print("\nFAILURES:")
        print("\n".join(failures))
    return len(failures) == 0


# ── Router Tests ──────────────────────────────────────────────────

def test_router_commands():
    """Commands in agent channels should route to COMMAND with target agent."""
    router = Router(
        ops_channel_id="C_OPS",
        channel_agents={"C_TEST": ["tester"], "C_MULTI": ["alice", "bob"]},
        agent_hosts={"tester": "host1", "alice": "host1", "bob": "host1"},
        local_agents={"tester", "alice", "bob"},
        local_host_id="host1",
    )
    cases = [
        ("!roster", "C_TEST", RouteAction.COMMAND, "tester"),
        ("!help", "C_TEST", RouteAction.COMMAND, "tester"),
        ("!search foo", "C_TEST", RouteAction.COMMAND, "tester"),
        ("!cancel", "C_MULTI", RouteAction.COMMAND, "alice"),
        ("hello there", "C_TEST", RouteAction.AGENT_QUERY, "tester"),
        ("> /status", "C_TEST", RouteAction.CLI_PASSTHROUGH, "tester"),
    ]
    failures = []
    for text, channel, expected_action, expected_agent in cases:
        result = router.route(text, channel, "U_USER")
        ok = result.action == expected_action and result.target_agent == expected_agent
        status = "OK" if ok else "FAIL"
        print(f"  {status}: '{text}' in {channel} -> {result.action.name}, agent={result.target_agent}")
        if not ok:
            failures.append(f"  Expected {expected_action.name}/{expected_agent}, got {result.action.name}/{result.target_agent}")
    return len(failures) == 0


def test_router_ignores_unknown_channels():
    """Messages in channels without agents should be ignored."""
    router = Router(
        ops_channel_id="C_OPS",
        channel_agents={"C_TEST": ["tester"]},
        agent_hosts={"tester": "host1"},
        local_agents={"tester"},
        local_host_id="host1",
    )
    result = router.route("!help", "C_UNKNOWN", "U_USER")
    ok = result.action == RouteAction.IGNORE
    print(f"  {'OK' if ok else 'FAIL'}: unknown channel -> {result.action.name}")
    return ok


def test_router_ops_channel():
    """Ops channel should handle commands but ignore plain text."""
    router = Router(
        ops_channel_id="C_OPS",
        channel_agents={"C_TEST": ["tester"]},
        agent_hosts={"tester": "host1"},
        local_agents={"tester"},
        local_host_id="host1",
    )
    r1 = router.route("!agents", "C_OPS", "U_USER")
    r2 = router.route("hello", "C_OPS", "U_USER")
    ok1 = r1.action == RouteAction.COMMAND
    ok2 = r2.action == RouteAction.IGNORE
    print(f"  {'OK' if ok1 else 'FAIL'}: ops !agents -> {r1.action.name}")
    print(f"  {'OK' if ok2 else 'FAIL'}: ops plain text -> {r2.action.name}")
    return ok1 and ok2


# ── Command Handler Tests ─────────────────────────────────────────

def test_handler_dispatch():
    """All documented commands must have a handler method."""
    commands = [
        "help", "agents", "status", "roster", "cost",
        "search", "cancel", "pause", "unpause",
        "pin", "pins", "unpin", "memory", "context", "history",
        "test", "sessions", "export", "import", "fork",
    ]
    # Create a minimal handler to check method existence
    handler = CommandHandler.__new__(CommandHandler)
    failures = []
    for cmd in commands:
        method = getattr(handler, f"_cmd_{cmd}", None)
        if method is None:
            failures.append(f"  MISSING: _cmd_{cmd}")
            print(f"  FAIL: _cmd_{cmd} not found")
        else:
            print(f"  OK: _cmd_{cmd} exists")
    if failures:
        print("\nMISSING HANDLERS:")
        print("\n".join(failures))
    return len(failures) == 0


# ── Event Dedup Tests ─────────────────────────────────────────────

def test_event_dedup():
    """Verify the _seen_events dedup mechanism works."""
    import re as re_mod

    # Simulate the dedup logic from hub.py
    _seen_events = set()
    _SEEN_MAX = 500

    results = []
    for event_ts in ["ts1", "ts2", "ts1", "ts3", "ts2"]:
        if event_ts in _seen_events:
            results.append(("DEDUP", event_ts))
            continue
        _seen_events.add(event_ts)
        if len(_seen_events) > _SEEN_MAX:
            to_remove = list(_seen_events)[:_SEEN_MAX // 2]
            for k in to_remove:
                _seen_events.discard(k)
        results.append(("PROCESS", event_ts))

    expected = [("PROCESS", "ts1"), ("PROCESS", "ts2"), ("DEDUP", "ts1"), ("PROCESS", "ts3"), ("DEDUP", "ts2")]
    ok = results == expected
    for r in results:
        print(f"  {r[0]}: {r[1]}")
    print(f"  {'OK' if ok else 'FAIL'}: dedup logic correct")
    return ok


# ── Run All ───────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("Command Parsing", test_parse_commands),
        ("Mention Stripping", test_parse_with_mention_stripped),
        ("HTML Entity Unescaping", test_parse_html_entities),
        ("Router: Commands", test_router_commands),
        ("Router: Unknown Channels", test_router_ignores_unknown_channels),
        ("Router: Ops Channel", test_router_ops_channel),
        ("Handler Dispatch", test_handler_dispatch),
        ("Event Dedup", test_event_dedup),
    ]

    all_pass = True
    for name, test_fn in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            passed = test_fn()
            if not passed:
                all_pass = False
                print(f">>> FAILED <<<")
            else:
                print(f">>> PASSED <<<")
        except Exception as e:
            all_pass = False
            print(f">>> ERROR: {e} <<<")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    if all_pass:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print(f"{'='*60}")
    sys.exit(0 if all_pass else 1)
