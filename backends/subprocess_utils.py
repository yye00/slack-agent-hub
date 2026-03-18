"""Shared async subprocess helpers for CLI backend adapters."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator


def build_env(extras: dict[str, str] | None = None) -> dict[str, str]:
    """Build an environment dict for subprocess execution.

    Inherits critical variables from the current environment
    and merges any backend-specific extras.
    """
    inherited_keys = [
        "PATH", "HOME", "USER", "SHELL", "LANG", "TERM",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
        "NODE_PATH", "NVM_DIR", "VOLTA_HOME",
    ]
    env = {k: os.environ[k] for k in inherited_keys if k in os.environ}
    if extras:
        env.update(extras)
    return env


async def run_cli_query(
    cmd: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float | None = 300.0,
) -> AsyncIterator[str]:
    """Spawn a CLI subprocess and yield stdout lines as they arrive.

    Args:
        cmd: Command and arguments to execute.
        env: Environment variables (use build_env() to construct).
        cwd: Working directory for the subprocess.
        timeout: Max seconds before killing the process. None = no timeout.

    Yields:
        Each line from stdout (stripped of trailing newline).

    Raises:
        FileNotFoundError: If the command binary doesn't exist.
        asyncio.TimeoutError: If the process exceeds timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )

    try:
        deadline = asyncio.get_event_loop().time() + timeout if timeout else None

        while True:
            if deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    proc.terminate()
                    raise asyncio.TimeoutError(f"CLI process exceeded {timeout}s timeout")
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    proc.terminate()
                    raise asyncio.TimeoutError(f"CLI process exceeded {timeout}s timeout")
            else:
                line = await proc.stdout.readline()

            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n")

    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
