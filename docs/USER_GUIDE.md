# Slack Agent Hub — User Guide

## Architecture

The hub connects to your Slack workspace and runs AI agents that respond to messages in channels. Each agent has a **backend** (Claude, Codex, or Gemini), a **working directory**, and serves one or more **channels**.

### Channels

- **Ops channel** (`#claude-ops`) — Central management. All `!commands` work here, but no agent queries. Use this to spawn agents, check status across all channels, reload config, etc.
- **Agent channels** — Any channel with agents assigned. Messages in these channels are routed to the appropriate agent. Commands also work here and target the channel's default agent.

### Backends

| Backend | CLI | Default Model | Auth |
|---------|-----|---------------|------|
| claude | `claude` | claude-sonnet-4-5 | Claude Code login |
| codex | `codex` | ChatGPT default | ChatGPT account |
| gemini | `gemini` | auto-gemini-3 | Google account |

## Talking to Agents

### Direct address (single agent responds)
```
Skippy: what files are in the project?
tester: run the tests
@Ziggy explain this code
Rex@fedora: what do you think?
```

Both display names (`Skippy`, `Ziggy`, `Rex`) and internal names (`tester`, `debater`, `contrarian`) work.

### Broadcast (all agents respond concurrently)
```
Everyone: summarize your current task
```

### Discussion / Debate (multi-round)
```
Debate: Is TDD worth it? --rounds 3
Discuss: best approach to refactor the auth module
```
Round 1: all agents respond concurrently. Round 2+: agents respond sequentially, seeing what others said.

### Inter-agent handoff
Agents can hand off to each other by including `@Name@host: message` in their response. The hub detects this and routes the message to the target agent automatically.

## Commands

All commands start with `!` and work in any agent channel or the ops channel.

### Agent Management
| Command | Description |
|---------|-------------|
| `!agents` | Quick list of all agents and status |
| `!status [agent]` | Detailed status (no arg = all agents in channel) |
| `!spawn <name> [options]` | Create a new agent dynamically |
| `!pause [agent]` | Pause an agent |
| `!unpause [agent]` | Resume a paused agent |
| `!cancel [agent]` | Cancel active query |
| `!restart [agent]` | Clear session and start fresh |

### Spawning Agents

From the ops channel or any agent channel:
```
!spawn helper --backend=claude --cwd=/home/captain/work/myproject --channel=#slack-agent-hub
!spawn reviewer --backend=gemini --cwd=/home/captain/work/swe --profile=ops
!spawn coder --backend=codex --cwd=/tmp/sandbox
```

Options:
- `--backend=claude|codex|gemini` (default: claude)
- `--model=<model>` (default: backend's default)
- `--cwd=<directory>` (default: /home/captain)
- `--channel=#channel-name` (default: current channel)
- `--profile=dev|ops|read-only` (default: dev)
- `--name=DisplayName` (default: capitalized internal name)

### Session Management
| Command | Description |
|---------|-------------|
| `!new [label] [--model=<model>]` | Start fresh session |
| `!sessions [agent]` | List sessions with name, UUID, age |
| `!resume <session_id>` | Resume a previous session |
| `!refresh` | New session, keep old in history |
| `!export <session_id>` | Export session as JSON |
| `!fork <session_id>` | Clone session for experimentation |

### Context & Memory
| Command | Description |
|---------|-------------|
| `!pin <text>` | Pin persistent context for the channel |
| `!pins` | List pinned context |
| `!unpin <id>` | Remove a pin |
| `!memory [agent]` | Show agent's memory file |
| `!history [N]` | Last N channel messages |
| `!context [N]` | Fetch channel context |
| `!search <keyword>` | Search channel history |

### Diagnostics
| Command | Description |
|---------|-------------|
| `!health` | Hub health summary |
| `!diag [agent]` | Deep diagnostic |
| `!logs [agent] [N]` | Last N log lines |
| `!test [agent]` | Verify backend responds |
| `!cost [agent]` | Token usage and costs |
| `!roster` | Full agent roster with channels |

### Admin
| Command | Description |
|---------|-------------|
| `!reload` | Reload config.yaml |
| `!audit [N]` | Show audit log entries |

### CLI Passthrough
```
> /compact       — compact the conversation context
> /model          — check/switch model
> /cost           — show cost (Claude)
```

## Configuration

Agents are defined in `config.yaml`. Each agent specifies:
- `backend` — which AI backend to use
- `model` — model name
- `channels` — list of Slack channels to serve
- `cwd` — working directory
- `profile` — permission profile (dev, ops, read-only)
- `display_name` — human-friendly name shown in Slack

Profiles control what tools the agent can use and its permission mode.

## Visual Branding

Each agent gets a distinct colored sidebar in Slack messages. The footer shows `DisplayName · hostname │ session shortid`. System messages (roster announcements, debate headers) appear without sidebars.
