"""Slack file download and auto-upload."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

DEFAULT_FILE_DIR = "/tmp/slack-agent-hub-files"
TEXT_EXTENSIONS = {".txt", ".md", ".prompt", ".rst", ".log", ".py", ".js", ".ts", ".yaml", ".yml", ".json", ".toml"}
MAX_INLINE_SIZE = 500 * 1024  # 500KB
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB
SYSTEM_DIRS = {"/etc/", "/sys/", "/proc/", "/dev/"}
FILE_PATH_RE = re.compile(r"(?:^|[\s`*\"])((?:/[\w./-]+|~/[\w./-]+)\.\w+)")


async def download_slack_files(
    client: AsyncWebClient,
    files: list[dict],
    channel_id: str,
    file_dir: str = DEFAULT_FILE_DIR,
) -> list[dict]:
    """Download Slack file attachments and return metadata."""
    save_dir = Path(file_dir) / channel_id
    save_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for f in files:
        file_id = f.get("id", "")
        name = f.get("name", "unknown")
        dest = save_dir / f"{file_id}_{name}"

        if dest.exists():
            results.append({"path": str(dest), "name": name, "cached": True})
            continue

        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue

        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {os.environ.get('SLACK_BOT_TOKEN', '')}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        results.append({"path": str(dest), "name": name, "cached": False})
        except Exception as e:
            logger.error(f"Failed to download {name}: {e}")

    return results


def build_file_annotation(downloaded: list[dict]) -> str:
    """Build prompt annotation for downloaded files."""
    parts = []
    for f in downloaded:
        path = Path(f["path"])
        ext = path.suffix.lower()
        if ext in TEXT_EXTENSIONS and path.stat().st_size < MAX_INLINE_SIZE:
            content = path.read_text(errors="replace")
            parts.append(f'\n<attached_file name="{f["name"]}">\n{content}\n</attached_file>')
        else:
            parts.append(f"\n[Attached file: {f['name']} at {f['path']}]")
    return "\n".join(parts)


def extract_file_paths(text: str) -> list[str]:
    """Extract file paths from agent response for auto-upload."""
    paths = []
    for match in FILE_PATH_RE.finditer(text):
        p = match.group(1)
        p = os.path.expanduser(p)
        if any(p.startswith(sd) for sd in SYSTEM_DIRS):
            continue
        if os.path.isfile(p) and os.path.getsize(p) < MAX_UPLOAD_SIZE:
            paths.append(p)
    return paths
