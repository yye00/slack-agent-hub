# slack-agent-hub

Federated Slack-to-CLI-agent bridge. Connect Slack channels to Claude, Codex, and Gemini agents running on bare metal hosts.

## Quick Start

```bash
./setup.sh
# Edit config.yaml and .env with your SLACK_BOT_TOKEN and SLACK_APP_TOKEN
uv run python hub.py
```

## Architecture

The hub connects to Slack via Socket Mode and routes messages to AI agents. Each agent runs a CLI backend (Claude, Codex, or Gemini) as a subprocess, with full tool use and session persistence.

```
Slack Channel  ──►  Hub (router)  ──►  Agent  ──►  Backend CLI (claude/codex/gemini)
                        │
                   Ops Channel (#claude-ops)
                   - !spawn, !status, !help
                   - Hub-wide management
```

### Channels

- **Ops channel** (`#claude-ops`) — Central management. Run `!commands` here to spawn agents, check status, reload config. No agent queries — just control.
- **Agent channels** — Channels with agents assigned. Messages are routed to the appropriate agent. Commands work here too.

### Backends

| Backend | CLI Tool | Default Model | Auth |
|---------|----------|---------------|------|
| `claude` | `claude` | claude-sonnet-4-5 | Claude Code login |
| `codex` | `codex` | ChatGPT default | ChatGPT account |
| `gemini` | `gemini` | auto-gemini-3 | Google account |

## Getting Started

### Option 1: Config file (pre-defined agents)

Define agents in `config.yaml`:

```yaml
ops_channel: "#claude-ops"

backends:
  claude:
    module: backends.claude
    default_model: claude-sonnet-4-5
  codex:
    module: backends.codex
    default_model: codex
  gemini:
    module: backends.gemini
    default_model: auto-gemini-3

agents:
  helper:
    display_name: Helper
    backend: claude
    model: claude-sonnet-4-5
    channels: ["#my-channel"]
    cwd: /home/user/work/myproject
    profile: dev

profiles:
  dev:
    allowed_tools: [Read, Write, Edit, Bash, LS, Grep, Glob]
    permission_mode: acceptEdits
  ops:
    allowed_tools: [Read, Write, Edit, Bash, LS, Grep, Glob, WebFetch, WebSearch]
    permission_mode: acceptEdits
```

### Option 2: Dynamic spawning (no agents in config)

Start with a minimal config — just backends, profiles, and the ops channel:

```yaml
ops_channel: "#claude-ops"

backends:
  claude:
    module: backends.claude
    default_model: claude-sonnet-4-5
  codex:
    module: backends.codex
    default_model: codex
  gemini:
    module: backends.gemini
    default_model: auto-gemini-3

agents: {}

profiles:
  dev:
    allowed_tools: [Read, Write, Edit, Bash, LS, Grep, Glob]
    permission_mode: acceptEdits
  ops:
    allowed_tools: [Read, Write, Edit, Bash, LS, Grep, Glob, WebFetch, WebSearch]
    permission_mode: acceptEdits
```

Then go to `#claude-ops` in Slack and spawn agents on the fly:

```
!spawn coder --backend=claude --cwd=/home/user/work/myproject --channel=#dev
!spawn reviewer --backend=gemini --cwd=/home/user/work/myproject --channel=#dev
!spawn assistant --backend=codex --cwd=/tmp --channel=#general
```

## Talking to Agents

### Direct address
```
Skippy: what files are in the project?
@Ziggy explain this code
Rex@fedora: what do you think?
tester: run the tests
```
Both display names and internal names work. In multi-agent channels, you must address an agent by name.

### Broadcast
```
Everyone: summarize your current task
```

### Multi-agent discussion
```
Debate: Is TDD worth it? --rounds 3
Discuss: best approach to refactor the auth module
```
Round 1: all agents respond concurrently. Round 2+: sequential, each agent sees prior responses.

### Inter-agent handoff
Agents can hand off to each other by including `@Name@host: message` in their response. The hub detects this and routes automatically.

## Commands

All commands start with `!`. Run from any agent channel or the ops channel.

### Agent Management
| Command | Description |
|---------|-------------|
| `!status` | Show all agents in channel with status |
| `!status <agent>` | Detailed status for one agent |
| `!agents` | Quick list of all agents |
| `!spawn <name> [opts]` | Spawn new agent (see below) |
| `!pause [agent]` | Pause an agent |
| `!unpause [agent]` | Resume a paused agent |
| `!cancel [agent]` | Cancel active query |
| `!restart [agent]` | Clear session, start fresh |

### Spawn Options
```
!spawn <name> [--backend=claude|codex|gemini] [--model=<model>] [--cwd=<dir>]
              [--channel=#channel-name] [--profile=dev|ops] [--name=DisplayName]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--backend` | claude | AI backend |
| `--model` | backend default | Model override |
| `--cwd` | /home/captain | Working directory |
| `--channel` | current channel | Target channel |
| `--profile` | dev | Permission profile |
| `--name` | capitalized name | Display name |

### Session Management
| Command | Description |
|---------|-------------|
| `!new [label] [--model=<model>]` | Fresh session |
| `!sessions [agent]` | List sessions |
| `!resume <session_id>` | Resume previous session |
| `!refresh` | New session, keep history |
| `!fork <session_id>` | Clone session |

### Context & Memory
| Command | Description |
|---------|-------------|
| `!pin <text>` | Pin context for channel |
| `!pins` | List pinned context |
| `!memory [agent]` | Show agent memory |
| `!history [N]` | Recent channel messages |
| `!search <keyword>` | Search channel history |

### Diagnostics & Admin
| Command | Description |
|---------|-------------|
| `!health` | Hub health summary |
| `!diag [agent]` | Deep diagnostic |
| `!cost [agent]` | Token usage |
| `!roster` | Full roster with channels |
| `!reload` | Reload config.yaml |
| `!help` | Full command list |

### CLI Passthrough
```
> /compact    — compact conversation context
> /model      — check/switch model
> /cost       — show cost (Claude)
```

## Visual Branding

Each agent gets a distinct colored sidebar in Slack. Footers show `DisplayName · hostname | session shortid`. System messages (roster, debate headers) appear without sidebars for clear visual separation.

## Multi-Agent Channels

Multiple agents can share a channel. Address them by name:
```
Skippy: write the tests       (Claude)
Ziggy: review the code        (Codex)
Rex: what could go wrong?     (Gemini)
```

Use `!status` to see all agents and their backends. Use `Debate:` for structured multi-round discussions.
