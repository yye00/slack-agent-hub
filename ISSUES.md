# slack-agent-hub — Issues & Missing Features

Last updated: 2026-03-16

---

## Tier 1 — Blocking real usage

### 1. OAuth token not passed to Claude backend
**Status:** Not implemented
The `CLAUDE_CODE_OAUTH_TOKEN` env var is not forwarded to the Claude backend when starting sessions. Queries will fail.

### 2. Multi-host message deduplication
**Status:** Not implemented
All orchestrators receive all Slack messages via Socket Mode. Currently:
- Unaddressed messages in a channel served by agents on **multiple hosts** will trigger responses from **every host**.
- `@Name@host` addressing is not parsed by the router — falls through to unaddressed handling.
- Need: `_detect_direct_address` must parse `Name@host` format. If addressed to another host, return IGNORE. If unaddressed and multiple hosts serve the channel, require explicit addressing.

### 3. Thread-based session mapping
**Status:** Not implemented
Slacker maps each Slack thread to a separate Claude session. slack-agent-hub currently uses one session per agent with no thread awareness. Users expect new threads to start fresh sessions and existing threads to resume.

### 4. Slack `files:write` scope
**Status:** Unknown
Auto-upload of referenced files requires `files:write` scope on the Slack app. May not be configured on the current Slack app.

---

## Tier 2 — Feature parity with slacker

### 5. Colored sidebar branding
**Status:** Done (SlackPoster with host_color)

### 6. Runtime config reload (`!reload`)
**Status:** Not implemented
Currently requires full service restart for any config change. Need `!reload` command to re-read config.yaml and apply agent/profile changes without dropping the Socket Mode connection.

### 7. Help docs per context
**Status:** Incomplete
- Ops channel commands vs in-channel commands not separated
- No flag documentation (`--model`, `--chrome`)
- No usage examples
- No explanation of profiles and what they allow

### 8. Missing commands from slacker
**Status:** Not implemented
Commands that exist in slacker but not in slack-agent-hub:
- `!context` — fetch and summarize channel transcript
- `!search` — search channel history by keyword
- `!history` — show recent channel messages
- `!watch` / `!monitor` / `!monitors` / `!stop` — file/process monitoring
- `!restart` — restart an agent
- `!reload` — reload config
- `!roster` / `!dashboard` — federation commands

### 9. Cost tracking during queries
**Status:** Schema exists, not wired
The `cost_log` table exists in SQLite but `QueryEngine` doesn't log costs after queries complete. Need to capture token usage from backend events and write to `cost_log`.

### 10. Gemini backend adapter
**Status:** Not implemented
Subprocess-based adapter for Google Gemini CLI. Interface defined in `backends/base.py`.

### 11. Codex backend adapter
**Status:** Not implemented
Subprocess-based adapter for OpenAI Codex CLI. Interface defined in `backends/base.py`.

---

## Tier 3 — Nice to have

### 12. Session export/import
Save/load session state across hosts.

### 13. Session branching/forking
Fork a session at a specific point for experimentation.

### 14. Per-user permissions / audit log
Schema placeholder exists in config. Not enforced.

### 15. Rate limiting
Prevent abuse of expensive operations.

### 16. Monitor web UI / webhook alerts
External notification channels beyond Slack.

### 17. Auto-save to memory
Automatically append session summaries to agent MEMORY.md.

### 18. Structured logging / log rotation
Currently logs to stdout. Need structured JSON logging and rotation for production.

### 19. Multi-workspace support
Single orchestrator serving multiple Slack workspaces.

---

## Recently Fixed
- ✅ Host-branded message posting with colored sidebar (2026-03-16)
- ✅ `host_color` config field (2026-03-16)
- ✅ `display_name` and `resume_session` config fields (2026-03-16)
- ✅ `host_id` auto-detection from hostname (2026-03-16)
