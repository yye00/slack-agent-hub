"""Hub health monitoring — periodic heartbeat and on-demand health reports."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent
    from slack_io.posting import SlackPoster

logger = logging.getLogger(__name__)


def build_health_report(agents: dict[str, "Agent"], host_id: str) -> str:
    """Build a health report string for the hub."""
    active = sum(1 for a in agents.values() if a.status == "active")
    paused = sum(1 for a in agents.values() if a.status == "paused")
    total = len(agents)

    in_flight = sum(
        1 for a in agents.values()
        if a._active_query_task and not a._active_query_task.done()
    )

    # Memory usage
    try:
        import resource
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        mem_mb = 0

    # Agent details
    agent_lines = []
    for name, agent in agents.items():
        status_icon = {"active": "🟢", "paused": "🟡"}.get(agent.status, "🔴")
        session = f"`{agent.current_session_id[:8]}…`" if agent.current_session_id else "none"
        query = "⏳" if (agent._active_query_task and not agent._active_query_task.done()) else "—"
        agent_lines.append(
            f"  {status_icon} {agent.display_name} │ {agent.backend.name} │ session: {session} │ query: {query}"
        )

    lines = [
        f"*Hub health — {host_id}*",
        f"Agents: {active} active, {paused} paused ({total} total) │ Queries in flight: {in_flight}",
        f"Memory: {mem_mb:.0f} MB",
        "",
        *agent_lines,
    ]
    return "\n".join(lines)


def check_anomalies(agents: dict[str, "Agent"]) -> list[str]:
    """Check for anomalies and return alert messages."""
    alerts = []
    for name, agent in agents.items():
        # Check for crashed query tasks
        task = agent._active_query_task
        if task and task.done() and not task.cancelled():
            try:
                exc = task.exception()
                if exc:
                    alerts.append(f"🚨 {agent.display_name}: query task crashed: {exc}")
            except Exception:
                pass

        # Check for agents that went offline
        if agent.status not in ("active", "paused"):
            alerts.append(f"🚨 {agent.display_name}: status is '{agent.status}'")

    return alerts


class HealthMonitor:
    """Periodic health heartbeat to ops channel."""

    def __init__(
        self,
        agents: dict[str, "Agent"],
        poster: "SlackPoster",
        ops_channel_id: str,
        host_id: str,
        interval_secs: int = 300,
    ):
        self._agents = agents
        self._poster = poster
        self._ops_channel_id = ops_channel_id
        self._host_id = host_id
        self._interval = interval_secs
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the periodic health heartbeat."""
        if self._ops_channel_id:
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Stop the periodic heartbeat."""
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                # Check for anomalies first
                alerts = check_anomalies(self._agents)
                if alerts:
                    alert_text = "\n".join(alerts)
                    await self._poster.post(
                        channel=self._ops_channel_id,
                        text=alert_text,
                    )

                # Regular health report
                report = build_health_report(self._agents, self._host_id)
                await self._poster.post(
                    channel=self._ops_channel_id,
                    text=report,
                )
            except Exception as e:
                logger.error(f"Health heartbeat failed: {e}")
