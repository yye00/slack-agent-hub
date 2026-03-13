# slack-agent-hub

Federated Slack-to-CLI-agent bridge. Connect Slack channels to Claude, Codex, and Gemini agents running on bare metal hosts.

## Quick Start

```bash
./setup.sh
# Edit config.yaml and .env
uv run python hub.py
```

See the design specification in the companion `slacker` repo at `docs/superpowers/specs/2026-03-13-slack-agent-hub-design.md`.
