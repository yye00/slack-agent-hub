"""End-to-end Slack hub test harness.

Sends commands via Chrome bridge, verifies responses via Slack API.
Run with: uv run python tests/e2e_slack_test.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time

# Channel IDs
CH_HUB = "C0AM37JU6QZ"      # #slack-agent-hub
CH_OPS = "C0AHENR129W"      # #claude-ops
BOT_USER = "U0AGE1EMBR9"

def load_token():
    """Load SLACK_BOT_TOKEN from .env"""
    with open(".env") as f:
        for line in f:
            if line.startswith("SLACK_BOT_TOKEN="):
                return line.strip().split("=", 1)[1].strip('"').strip("'")
    raise RuntimeError("No SLACK_BOT_TOKEN in .env")

TOKEN = load_token()


def slack_api(method: str, params: dict) -> dict:
    """Call Slack Web API."""
    import urllib.request
    url = f"https://slack.com/api/{method}"
    if method.startswith("conversations."):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    else:
        data = json.dumps(params).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_messages(channel: str, limit: int = 5, oldest: str = "") -> list[dict]:
    """Get recent messages from a channel."""
    params = {"channel": channel, "limit": str(limit)}
    if oldest:
        params["oldest"] = oldest
    data = slack_api("conversations.history", params)
    return data.get("messages", [])


def find_bot_response(channel: str, after_ts: str, timeout: float = 15.0, keyword: str = "") -> dict | None:
    """Wait for a bot response after a given timestamp."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = get_messages(channel, limit=5, oldest=after_ts)
        for m in msgs:
            if m.get("user") == BOT_USER or m.get("bot_id"):
                text = m.get("text", "")
                att_text = " ".join(a.get("text", "") for a in m.get("attachments", []))
                full = text + " " + att_text
                if keyword and keyword.lower() not in full.lower():
                    continue
                return m
        time.sleep(2)
    return None


def get_response_text(msg: dict) -> str:
    """Extract full text from a message including attachments."""
    parts = []
    if msg.get("text", "").strip():
        parts.append(msg["text"])
    for a in msg.get("attachments", []):
        if a.get("text"):
            parts.append(a["text"])
    return "\n".join(parts)


def post_as_bot(channel: str, text: str) -> str:
    """Post a message as the bot (won't be processed by hub — for testing API only)."""
    data = slack_api("chat.postMessage", {"channel": channel, "text": text})
    return data.get("ts", "")


class TestResult:
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        s = f"  [{status}] {self.name}"
        if self.detail:
            s += f"\n         {self.detail}"
        return s


def run_tests_via_api():
    """Run tests that can be verified via API without sending user messages.

    These test the command handler directly by checking existing state.
    """
    results = []

    # Test: DB has sessions for multiple agents
    print("Testing session data in DB...")
    import sqlite3
    conn = sqlite3.connect("hub.db")
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT agent_name, COUNT(*) as cnt FROM sessions WHERE archived=0 GROUP BY agent_name").fetchall()
    agents_with_sessions = {r["agent_name"]: r["cnt"] for r in rows}

    results.append(TestResult(
        "DB: multiple agents have sessions",
        len(agents_with_sessions) >= 3,
        f"Agents: {dict(agents_with_sessions)}"
    ))

    # Test: session name lookup
    row = conn.execute("SELECT id, name FROM sessions WHERE name='say-hello' AND agent_name='tester'").fetchone()
    results.append(TestResult(
        "DB: session 'say-hello' exists for tester",
        row is not None,
        f"ID: {row['id'][:8] if row else 'NOT FOUND'}"
    ))

    # Test: get_session resolves by name
    sys.path.insert(0, ".")
    import asyncio as aio
    from storage.db import Database

    async def test_db():
        db = Database("hub.db")
        await db.initialize()

        # By name
        s = await db.get_session("say-hello", agent_name="tester")
        results.append(TestResult(
            "get_session: resolves by name",
            s is not None and s["name"] == "say-hello",
            f"Found: {s['id'][:8] if s else 'None'}"
        ))

        # By prefix
        if row:
            prefix = row["id"][:8]
            s2 = await db.get_session(prefix)
            results.append(TestResult(
                f"get_session: resolves by prefix '{prefix}'",
                s2 is not None,
                f"Found: {s2['id'][:8] if s2 else 'None'}"
            ))

        # Nonexistent
        s3 = await db.get_session("nonexistent-xyz", agent_name="tester")
        results.append(TestResult(
            "get_session: returns None for nonexistent",
            s3 is None,
            f"Got: {s3}"
        ))

        # List sessions for agent
        sessions = await db.list_sessions("tester")
        results.append(TestResult(
            "list_sessions: returns multiple for tester",
            len(sessions) > 1,
            f"Count: {len(sessions)}"
        ))

        # List sessions for all agents in channel
        for agent_name in ["tester", "debater", "contrarian"]:
            s = await db.list_sessions(agent_name)
            results.append(TestResult(
                f"list_sessions: {agent_name} has sessions",
                len(s) > 0,
                f"Count: {len(s)}"
            ))

    aio.run(test_db())
    conn.close()
    return results


def run_command_handler_tests():
    """Test the command handler directly with mocks."""
    import asyncio as aio
    import unittest.mock as mock
    sys.path.insert(0, ".")

    from storage.db import Database
    from core.command_handler import CommandHandler

    results = []

    async def test():
        db = Database("hub.db")
        await db.initialize()

        # Create mock agents
        def make_agent(name, display, backend_name="claude"):
            a = mock.MagicMock()
            a.name = name
            a.display_name = display
            a.status = "active"
            a.current_session_id = None
            a.backend = mock.AsyncMock()
            a.backend.name = backend_name
            a.backend.resume_session = mock.AsyncMock(return_value=True)
            return a

        agents = {
            "tester": make_agent("tester", "Skippy"),
            "debater": make_agent("debater", "Ziggy", "codex"),
            "contrarian": make_agent("contrarian", "Rex", "gemini"),
        }

        poster = mock.AsyncMock()
        handler = CommandHandler(
            agents=agents, db=db, slack_client=mock.AsyncMock(),
            poster=poster,
            channel_agents={CH_HUB: ["tester", "debater", "contrarian"]},
        )

        # Test: !agents
        poster.post.reset_mock()
        await handler.handle("agents", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!agents: lists all 3 channel agents",
            "Skippy" in text and "Ziggy" in text and "Rex" in text,
            f"Response: {text[:100]}"
        ))

        # Test: !status (no args) — all channel agents
        poster.post.reset_mock()
        await handler.handle("status", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!status: shows all 3 channel agents",
            "Skippy" in text and "Ziggy" in text and "Rex" in text,
            f"Has all names: {'Skippy' in text}, {'Ziggy' in text}, {'Rex' in text}"
        ))

        # Test: !status tester — single agent
        poster.post.reset_mock()
        await handler.handle("status", ["tester"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!status tester: shows single agent",
            "Skippy" in text,
            f"Response: {text[:100]}"
        ))

        # Test: !status nonexistent
        poster.post.reset_mock()
        await handler.handle("status", ["nonexistent"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!status nonexistent: shows error",
            "unknown" in text.lower() or "Unknown" in text,
            f"Response: {text[:100]}"
        ))

        # Test: !sessions (channel scoped)
        poster.post.reset_mock()
        await handler.handle("sessions", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        has_skippy = "Skippy" in text
        has_ziggy = "Ziggy" in text
        has_rex = "Rex" in text
        results.append(TestResult(
            "!sessions: shows all channel agents' sessions",
            has_skippy and has_ziggy and has_rex,
            f"Skippy:{has_skippy} Ziggy:{has_ziggy} Rex:{has_rex}"
        ))

        # Test: !sessions tester
        poster.post.reset_mock()
        await handler.handle("sessions", ["tester"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!sessions tester: shows only Skippy",
            "Skippy" in text and "Ziggy" not in text,
            f"Response length: {len(text)}, has Ziggy: {'Ziggy' in text}"
        ))

        # Test: !sessions all
        poster.post.reset_mock()
        await handler.handle("sessions", ["all"], {}, CH_OPS, None, "", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!sessions all: shows all agents hub-wide",
            "Skippy" in text and "Ziggy" in text and "Rex" in text,
            f"Length: {len(text)}"
        ))

        # Test: !sessions nonexistent
        poster.post.reset_mock()
        await handler.handle("sessions", ["nonexistent"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!sessions nonexistent: shows no sessions",
            "no session" in text.lower() or text == "" or poster.post.call_args is not None,
            f"Response: {text[:100]}"
        ))

        # Test: !resume say-hello (by name)
        poster.post.reset_mock()
        agents["tester"].backend.resume_session.reset_mock()
        await handler.handle("resume", ["say-hello"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        resume_called = agents["tester"].backend.resume_session.called
        if resume_called:
            sid = agents["tester"].backend.resume_session.call_args[0][0]
            # Verify it's a real UUID, not "say-hello"
            is_uuid = len(sid) > 20 and "-" in sid
        else:
            sid = ""
            is_uuid = False
        results.append(TestResult(
            "!resume say-hello: resolves name to UUID",
            resume_called and is_uuid,
            f"Called: {resume_called}, SID: {sid[:16]}, Reply: {text[:80]}"
        ))

        # Test: !resume by ID prefix
        poster.post.reset_mock()
        agents["tester"].backend.resume_session.reset_mock()
        import sqlite3
        conn = sqlite3.connect("hub.db")
        row = conn.execute("SELECT id FROM sessions WHERE agent_name='tester' LIMIT 1").fetchone()
        conn.close()
        if row:
            prefix = row[0][:8]
            await handler.handle("resume", [prefix], {}, CH_HUB, None, "tester", "U123")
            text = poster.post.call_args.kwargs.get("text", "")
            resume_called = agents["tester"].backend.resume_session.called
            results.append(TestResult(
                f"!resume {prefix}: resolves prefix to full ID",
                resume_called and "Resumed" in text,
                f"Reply: {text[:80]}"
            ))

        # Test: !resume nonexistent
        poster.post.reset_mock()
        agents["tester"].backend.resume_session.reset_mock()
        await handler.handle("resume", ["nonexistent-xyz"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        not_called = not agents["tester"].backend.resume_session.called
        results.append(TestResult(
            "!resume nonexistent-xyz: shows error, doesn't call backend",
            not_called and "no session" in text.lower(),
            f"Backend called: {not not_called}, Reply: {text[:100]}"
        ))

        # Test: !new
        poster.post.reset_mock()
        await handler.handle("new", ["test-session"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!new test-session: creates fresh session",
            "fresh" in text.lower() or "new" in text.lower() or "🆕" in text,
            f"Reply: {text[:100]}"
        ))

        # Test: !help
        poster.post.reset_mock()
        await handler.handle("help", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!help: returns help text",
            len(text) > 50 and ("command" in text.lower() or "!" in text),
            f"Response length: {len(text)}"
        ))

        # Test: unknown command
        poster.post.reset_mock()
        await handler.handle("xyzgarbage", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!xyzgarbage: shows unknown command error",
            "unknown" in text.lower(),
            f"Reply: {text[:100]}"
        ))

        # Test: !pin and !pins
        poster.post.reset_mock()
        await handler.handle("pin", ["Always", "use", "uv"], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!pin: pins context",
            "pin" in text.lower(),
            f"Reply: {text[:100]}"
        ))

        poster.post.reset_mock()
        await handler.handle("pins", [], {}, CH_HUB, None, "tester", "U123")
        text = poster.post.call_args.kwargs.get("text", "")
        results.append(TestResult(
            "!pins: lists pins",
            poster.post.called,
            f"Reply: {text[:100]}"
        ))

    aio.run(test())
    return results


def run_router_tests():
    """Test the router."""
    sys.path.insert(0, ".")
    from core.router import Router, RouteAction

    results = []

    router = Router(
        ops_channel_id=CH_OPS,
        channel_agents={CH_HUB: ["tester", "debater", "contrarian"]},
        agent_hosts={"tester": "fedora", "debater": "fedora", "contrarian": "fedora"},
        local_agents={"tester", "debater", "contrarian"},
        local_host_id="fedora",
        display_names={"tester": "Skippy", "debater": "Ziggy", "contrarian": "Rex"},
    )

    # Commands
    r = router.route("!agents", CH_HUB, "U123")
    results.append(TestResult("route: !agents -> COMMAND", r.action == RouteAction.COMMAND))

    r = router.route("!status", CH_OPS, "U123")
    results.append(TestResult("route: !status from ops -> COMMAND", r.action == RouteAction.COMMAND))

    # Plain text in ops -> IGNORE
    r = router.route("hello", CH_OPS, "U123")
    results.append(TestResult("route: plain text in ops -> IGNORE", r.action == RouteAction.IGNORE))

    # Unknown channel -> IGNORE
    r = router.route("hello", "C_UNKNOWN", "U123")
    results.append(TestResult("route: unknown channel -> IGNORE", r.action == RouteAction.IGNORE))

    # Direct address by display name
    r = router.route("Skippy: hello", CH_HUB, "U123")
    results.append(TestResult(
        "route: 'Skippy: hello' -> AGENT_QUERY to tester",
        r.action == RouteAction.AGENT_QUERY and r.target_agent == "tester",
        f"action={r.action}, target={r.target_agent}"
    ))

    # Direct address by internal name
    r = router.route("debater: hello", CH_HUB, "U123")
    results.append(TestResult(
        "route: 'debater: hello' -> AGENT_QUERY to debater",
        r.action == RouteAction.AGENT_QUERY and r.target_agent == "debater",
        f"action={r.action}, target={r.target_agent}"
    ))

    # Broadcast
    r = router.route("Everyone: do something", CH_HUB, "U123")
    results.append(TestResult(
        "route: broadcast -> BROADCAST",
        r.action == RouteAction.BROADCAST,
        f"action={r.action}, agents={r.broadcast_agents}"
    ))

    # CLI passthrough
    r = router.route("> /compact", CH_HUB, "U123")
    results.append(TestResult(
        "route: '> /compact' -> CLI_PASSTHROUGH",
        r.action == RouteAction.CLI_PASSTHROUGH,
        f"action={r.action}"
    ))

    # Discuss
    r = router.route("Debate: is TDD worth it?", CH_HUB, "U123")
    results.append(TestResult(
        "route: 'Debate: ...' -> DISCUSS",
        r.action == RouteAction.DISCUSS,
        f"action={r.action}"
    ))

    # Handoff
    r = router.route("@Rex@fedora: take over", CH_HUB, "U123")
    results.append(TestResult(
        "route: handoff -> HANDOFF_LOCAL",
        r.action == RouteAction.HANDOFF_LOCAL and r.target_agent == "contrarian",
        f"action={r.action}, target={r.target_agent}"
    ))

    return results


def run_parse_tests():
    """Test command parsing edge cases."""
    sys.path.insert(0, ".")
    from core.commands import parse_message, MessageType

    results = []

    # Basic command
    p = parse_message("!agents")
    results.append(TestResult("parse: !agents", p.type == MessageType.COMMAND and p.command == "agents"))

    # Command with options (= format)
    p = parse_message("!spawn bob --backend=claude --cwd=/tmp --channel=#test")
    results.append(TestResult(
        "parse: spawn with = options",
        p.command == "spawn" and p.options.get("backend") == "claude" and p.options.get("channel") == "#test",
        f"options={p.options}, args={p.args}"
    ))

    # Command with options (space format)
    p = parse_message("!spawn bob --backend claude --cwd /tmp")
    results.append(TestResult(
        "parse: spawn with space options",
        p.options.get("backend") == "claude" and p.options.get("cwd") == "/tmp",
        f"options={p.options}"
    ))

    # Discuss with rounds
    p = parse_message("Debate: is TDD worth it? --rounds 3")
    results.append(TestResult(
        "parse: debate with rounds",
        p.type == MessageType.DISCUSS and p.options.get("rounds") == "3",
        f"type={p.type}, options={p.options}, text={p.text}"
    ))

    # Handoff
    p = parse_message("@Rex@fedora: here is context")
    results.append(TestResult(
        "parse: handoff",
        p.type == MessageType.HANDOFF and p.handoff_target == "rex" and p.handoff_host == "fedora",
        f"target={p.handoff_target}, host={p.handoff_host}"
    ))

    # CLI passthrough
    p = parse_message("> /model claude-opus-4-6")
    results.append(TestResult(
        "parse: CLI passthrough",
        p.type == MessageType.CLI_PASSTHROUGH and p.cli_command == "/model claude-opus-4-6",
        f"cli_command={p.cli_command}"
    ))

    # Broadcast
    p = parse_message("Everyone: summarize")
    results.append(TestResult(
        "parse: broadcast",
        p.type == MessageType.BROADCAST and "summarize" in p.text,
        f"text={p.text}"
    ))

    # Plain text
    p = parse_message("what files are here?")
    results.append(TestResult(
        "parse: plain text",
        p.type == MessageType.PLAIN_TEXT,
        f"type={p.type}"
    ))

    # Edge: ! alone (just exclamation)
    p = parse_message("!")
    results.append(TestResult(
        "parse: lone '!' -> not a command (no word after !)",
        p.type == MessageType.PLAIN_TEXT,
        f"type={p.type}, command={p.command}"
    ))

    # Edge: HTML entities (&amp; -> &, &lt; -> <)
    p = parse_message("!pin save &amp; exit")
    results.append(TestResult(
        "parse: HTML unescape &amp; -> &",
        p.command == "pin" and "save" in p.args and "&" in p.args,
        f"args={p.args}"
    ))

    p = parse_message("!pin use &lt;tag&gt;")
    results.append(TestResult(
        "parse: HTML unescape &lt;&gt; -> <>",
        p.command == "pin" and "<tag>" in " ".join(p.args),
        f"args={p.args}"
    ))

    return results


def main():
    print("=" * 60)
    print("SLACK AGENT HUB — END-TO-END TEST SUITE")
    print("=" * 60)

    all_results = []

    print("\n--- Command Parsing Tests ---")
    parse_results = run_parse_tests()
    all_results.extend(parse_results)
    for r in parse_results:
        print(r)

    print("\n--- Router Tests ---")
    router_results = run_router_tests()
    all_results.extend(router_results)
    for r in router_results:
        print(r)

    print("\n--- Database Tests ---")
    db_results = run_tests_via_api()
    all_results.extend(db_results)
    for r in db_results:
        print(r)

    print("\n--- Command Handler Tests ---")
    handler_results = run_command_handler_tests()
    all_results.extend(handler_results)
    for r in handler_results:
        print(r)

    # Summary
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print("\nFAILURES:")
        for r in all_results:
            if not r.passed:
                print(r)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
