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
**Status:** Done (2026-03-18)
`core/session_naming.py` generates kebab-case names from first prompt. Migration 002 adds `name` column. `!sessions` shows name, truncated UUID, age, status, last activity. `!status` displays session name alongside UUID. Migration system now tracks applied migrations for idempotency.

### 9. Hub health monitoring
**Status:** Done (2026-03-18)
`core/health.py` provides `HealthMonitor` with periodic heartbeat to ops (5 min default) and `build_health_report` for on-demand `!health`. Reports agents active/paused, queries in flight, memory usage. `check_anomalies` detects crashed query tasks and abnormal agent statuses.

### 10. Diagnostic commands
**Status:** Done (2026-03-18)
`!health` — hub health summary. `!logs [agent] [N]` — last N stderr lines (default 20). `!diag [agent]` — session state, backend, config, recent stderr. `!test [agent]` — sends trivial query to verify backend (requires active session).

### 11. Session continuity protection
**Status:** Done (2026-03-18)
`core/continuity.py` provides `build_resume_preamble` and `generate_session_summary`. Migration 003 adds `summary` and `ended_cleanly` columns. Summaries saved on session rotation and clean shutdown. Preamble injected into system prompt on new session if previous summary exists. Unclean shutdown preamble warns agent to verify state.

### 12. Runtime config reload (`!reload`)
**Status:** Done (2026-03-18)
`!reload` re-reads and validates config.yaml. Reports agent/profile counts. Agent/profile changes take effect on next session start. Socket Mode connection preserved.

### 13. Help docs per context
**Status:** Done (2026-03-18)
`!help` rewritten with organized categories (Agent, Session, Diagnostics, Memory & Context, Admin, CLI). Includes flag documentation (`--model`), usage patterns, and profile explanation.

### 14. Missing commands from slacker
**Status:** Done (2026-03-18)
Implemented: `!context`, `!search`, `!history`, `!restart`, `!reload`, `!roster`. Deferred: `!watch`/`!monitor`/`!stop` (file/process monitoring — Tier 3), `!dashboard` (federation dashboard — Tier 3).

### 15. Cost tracking during queries
**Status:** Done (2026-03-18)
`QueryEngine` captures `cost_usd`, `input_tokens`, `output_tokens` from backend `complete` events and logs to `cost_log` table. Claude backend extracts token counts from `ResultMessage`. Non-fatal — logging failures don't break queries.

### 16. Gemini backend adapter
**Status:** Done (2026-03-18)
`backends/gemini.py` wraps Gemini CLI in headless mode (`gemini -p --output-format stream-json --yolo`). Parses stream-json events into unified Event stream. Supports session resume via `-r`. Registered in `BACKEND_CLASSES`.

### 17. Codex backend adapter
**Status:** Done (2026-03-18)
`backends/codex.py` wraps Codex CLI in non-interactive mode (`codex exec --json`). Parses JSONL events into unified Event stream. Supports session resume via `codex exec resume`. Registered in `BACKEND_CLASSES`.

---

## Tier 3 — Nice to have

### 18. Session export/import
**Status:** Done (2026-03-18)
`!export [session_id]` dumps session state as JSON. `!import` accepts JSON payload to restore a session into the local DB. Supports cross-host session migration.

### 19. Session branching/forking
**Status:** Done (2026-03-18)
`!fork [session_id]` creates a new session with copied metadata from the source. Fork does not set current session — user must `!resume` explicitly to avoid orphan backend state.

### 20. Per-user permissions / audit log
**Status:** Done (2026-03-18)
`core/permissions.py` provides `PermissionChecker` with `PermLevel` enum (ADMIN, OPS, USER). Default command mappings enforce access on `!reload`/`!audit` (ADMIN), diagnostics (OPS). `log_audit()` writes to `audit_log` table. `!audit [N]` shows recent audit entries. Migration 004 creates audit_log table.

### 21. Rate limiting
**Status:** Done (2026-03-18)
`core/rate_limit.py` implements token bucket `RateLimiter` with per-user buckets. Configurable `max_queries_per_user` and `refill_per_sec` in `config.yaml`. `max_tokens=0` disables limiting. Checked before AGENT_QUERY dispatch in hub.py.

### 22. Monitor web UI / webhook alerts
**Status:** Not implemented
External notification channels beyond Slack. Requires separate design phase.

### 23. Auto-save to memory
**Status:** Done (2026-03-18)
After successful queries, `hub.py` generates a session summary via `generate_session_summary()` and appends it to the agent's `MEMORY.md` via `append_memory()`. Includes session name header. Non-fatal — failures logged at debug level.

### 24. Structured logging / log rotation
**Status:** Done (2026-03-18)
`core/structured_logging.py` provides `JsonFormatter` (single-line JSON) and `setup_logging()`. Configures stdout handler + `RotatingFileHandler` (10 MB, 5 backups, always JSON). Controlled via `JSON_LOGS` and `LOG_LEVEL` env vars.

### 25. Multi-workspace support
**Status:** Not implemented
Single orchestrator serving multiple Slack workspaces. Requires separate design phase.

---

## Recently Fixed
- ✅ Gemini CLI backend adapter with stream-json parsing (#16) (2026-03-18)
- ✅ Codex CLI backend adapter with JSONL parsing (#17) (2026-03-18)
- ✅ Session export/import and forking via !export, !import, !fork (2026-03-18)
- ✅ Structured JSON logging with rotation (2026-03-18)
- ✅ Auto-save session summaries to agent MEMORY.md (2026-03-18)
- ✅ Token bucket rate limiting per user (2026-03-18)
- ✅ Per-user permissions with audit log and !audit command (2026-03-18)
- ✅ Named sessions with auto-generated kebab-case names (2026-03-18)
- ✅ Cost tracking wired from backend events to cost_log DB (2026-03-18)
- ✅ Hub health monitoring with periodic heartbeat and anomaly alerts (2026-03-18)
- ✅ Diagnostic commands: !health, !diag, !logs, !test (2026-03-18)
- ✅ Session continuity protection with summary save and preamble injection (2026-03-18)
- ✅ Runtime config reload via !reload (2026-03-18)
- ✅ Missing slacker commands: !restart, !roster, !history, !context, !search (2026-03-18)
- ✅ Help docs rewritten with organized categories and flag documentation (2026-03-18)
- ✅ Idempotent migration system with registry-based tracking (2026-03-18)
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
