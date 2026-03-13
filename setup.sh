#!/usr/bin/env bash
set -euo pipefail

echo "=== slack-agent-hub setup ==="

# Check Python version
python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'" 2>/dev/null || {
    echo "ERROR: Python 3.11+ is required"
    exit 1
}

# Check uv
command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv is required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
}

# Install dependencies
echo "Installing dependencies..."
uv sync

# Create config from example if not exists
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "Created config.yaml from template — edit it with your agent definitions"
fi

# Create .env from example if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from template — add your Slack tokens"
fi

echo ""
echo "Setup complete! Next steps:"
echo "  1. Edit config.yaml with your agents"
echo "  2. Edit .env with your Slack tokens"
echo "  3. Run: uv run python hub.py"
