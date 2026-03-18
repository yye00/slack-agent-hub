# slack-agent-hub — Issues & Missing Features

Last updated: 2026-03-18

---

## Tier 1 — Blocking real usage

### 1. OAuth token not passed to Claude backend
**Status:** Done (2026-03-16)
`_build_env()` in `backends/claude.py` forwards `CLAUDE_CODE_OAUTH_TOKEN` to the CLI subprocess.

### 2. Multi-host message deduplication
**Status:** Done (2026-03-18)
Router parses `Name@host` addressing. Messages to remote hosts are ignored. Unaddressed messages in multi-host channels require explicit addressing. Plain-name addressing only matches local agents.

### 3. Thread-based task dispatch
**Status:** Done (2026-03-18)
Threaded replies dispatch as background tasks (`/btw` for Claude) via `core/thread_dispatch.py`. Main channel conversation stays in the primary session.

### 4. Slack `files:write` scope
**Status:** Done (2026-03-18)
Startup self-test probes `files_getUploadURLExternal` to verify `files:write` scope. Non-critical — reported but does not block startup.

### 5. Session lifecycle notifications
**Status:** Done (2026-03-18)
`core/lifecycle.py` posts session start/restart/death events to ops channel. Restarts also notify the agent's channel with previous session ID and reason.

### 6. Startup self-test
**Status:** Done (2026-03-18)
`core/selftest.py` verifies Slack API, ops channel, configured channels, backend CLIs, and files:write scope on startup. Posts results to ops. Blocks message acceptance on critical failure while keeping process alive.

---

## Tier 2 — Feature parity with slacker

### 7. Colored sidebar branding
**Status:** Done (SlackPoster with host_color)

### 8. Named sessions
**Status:** Not implemented
Sessions are identified only by UUIDs, making it impossible to tell what a session was doing. Need:
- Auto-generate a human-readable name from the first prompt (e.g., "dmrg-optimization-run").
- Store both UUID and name in the DB. Display name everywhere the UUID currently appears.
- `!sessions` command shows: name, UUID (truncated), age, status, last activity.

### 9. Hub health monitoring
**Status:** Not implemented
No way to know if the hub is healthy without SSH-ing into the host. Need:
- Periodic health heartbeat to ops channel (configurable interval, default 5 min).
- Report: agents active, queries in flight, memory usage, backend connectivity.
- Alert on: agent crash, backend unreachable, query timeout, high error rate.
- `!health` command for on-demand status.

### 10. Diagnostic commands
**Status:** Not implemented
When things go wrong, there's no way to inspect hub state from Slack. Need:
- `!health` — hub health summary (agents, backends, connections).
- `!logs [agent] [N]` — last N log lines for an agent (default 20).
- `!diag [agent]` — deep diagnostic: session state, pending queries, memory usage, backend status.
- `!test [agent]` — send a trivial query to verify the agent's backend is responsive.

### 11. Session continuity protection
**Status:** Not implemented
When a session dies, all context is lost. The new session starts cold. Need:
- Before a session ends (crash or clean shutdown), save a summary to the DB.
- On restart, inject a preamble: "You are resuming work. Previous session summary: ..."
- If session died uncleanly, note that in the preamble so the agent knows to verify state.

### 12. Runtime config reload (`!reload`)
**Status:** Not implemented
Currently requires full service restart for any config change. Need `!reload` command to re-read config.yaml and apply agent/profile changes without dropping the Socket Mode connection.

### 13. Help docs per context
**Status:** Incomplete
- Ops channel commands vs in-channel commands not separated
- No flag documentation (`--model`, `--chrome`)
- No usage examples
- No explanation of profiles and what they allow

### 14. Missing commands from slacker
**Status:** Not implemented
Commands that exist in slacker but not in slack-agent-hub:
- `!context` — fetch and summarize channel transcript
- `!search` — search channel history by keyword
- `!history` — show recent channel messages
- `!watch` / `!monitor` / `!monitors` / `!stop` — file/process monitoring
- `!restart` — restart an agent
- `!reload` — reload config
- `!roster` / `!dashboard` — federation commands

### 15. Cost tracking during queries
**Status:** Schema exists, not wired
The `cost_log` table exists in SQLite but `QueryEngine` doesn't log costs after queries complete. Need to capture token usage from backend events and write to `cost_log`.

### 16. Gemini backend adapter
**Status:** Not implemented
Subprocess-based adapter for Google Gemini CLI. Interface defined in `backends/base.py`.

### 17. Codex backend adapter
**Status:** Not implemented
Subprocess-based adapter for OpenAI Codex CLI. Interface defined in `backends/base.py`.

---

## Tier 3 — Nice to have

### 18. Session export/import
Save/load session state across hosts.

### 19. Session branching/forking
Fork a session at a specific point for experimentation.

### 20. Per-user permissions / audit log
Schema placeholder exists in config. Not enforced.

### 21. Rate limiting
Prevent abuse of expensive operations.

### 22. Monitor web UI / webhook alerts
External notification channels beyond Slack.

### 23. Auto-save to memory
Automatically append session summaries to agent MEMORY.md.

### 24. Structured logging / log rotation
Currently logs to stdout. Need structured JSON logging and rotation for production.

### 25. Multi-workspace support
Single orchestrator serving multiple Slack workspaces.

---

## Recently Fixed
- ✅ Multi-host message deduplication with Name@host addressing (2026-03-18)
- ✅ Thread-based task dispatch via /btw background commands (2026-03-18)
- ✅ Session lifecycle notifications to ops and agent channels (2026-03-18)
- ✅ Startup self-test with dependency verification (2026-03-18)
- ✅ files:write scope check in startup self-test (2026-03-18)
- ✅ OAuth token forwarding to Claude backend (2026-03-16)
- ✅ Host-branded message posting with colored sidebar (2026-03-16)
- ✅ `host_color` config field (2026-03-16)
- ✅ `display_name` and `resume_session` config fields (2026-03-16)
- ✅ `host_id` auto-detection from hostname (2026-03-16)
