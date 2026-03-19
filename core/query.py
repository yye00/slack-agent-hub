"""Query execution engine — runs backend queries with heartbeat and error handling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backends.base import Event
from core.heartbeat import HeartbeatState, TipRotator
from slack_io.messages import (
    chunk_response,
    format_completion,
    format_heartbeat,
)

if TYPE_CHECKING:
    from core.agent import Agent
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_io.posting import SlackPoster
    from storage.db import Database

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    text: str
    session_id: str
    success: bool
    error: str = ""
    tool_count: int = 0
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class QueryEngine:
    """Executes a query against an agent's backend with heartbeat tracking."""

    def __init__(
        self,
        agent: Agent,
        slack_client: AsyncWebClient,
        poster: SlackPoster,
        db: Database,
        heartbeat_interval: int = 15,
        stall_warn_mins: int = 5,
        tips_enabled: bool = True,
    ):
        self._agent = agent
        self._slack = slack_client
        self._poster = poster
        self._db = db
        self._heartbeat_interval = heartbeat_interval
        self._stall_threshold = stall_warn_mins * 60
        self._tips_enabled = tips_enabled

    async def execute(
        self,
        prompt: str,
        channel_id: str,
        thread_ts: str | None = None,
        session_id: str | None = None,
        tip_pool: list[str] | None = None,
    ) -> QueryResult:
        """Execute a query with heartbeat and error recovery."""
        agent = self._agent

        # Post placeholder (plain — heartbeat will brand it on first tick)
        reply_ts = thread_ts
        try:
            resp = await self._poster.post(
                channel=channel_id,
                text="⏳ Thinking...",
                thread_ts=reply_ts,
                agent_name=agent.name,
            )
            placeholder_ts = resp["ts"]
        except Exception as e:
            logger.error(f"Failed to post placeholder: {e}")
            return QueryResult(text="", session_id="", success=False, error=str(e))

        # Setup heartbeat state
        hb_state = HeartbeatState()
        tip_rotator = TipRotator(tip_pool or [], enabled=self._tips_enabled)

        # Start heartbeat loop
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                channel_id, placeholder_ts, reply_ts, hb_state, tip_rotator
            )
        )

        # Run query
        result = await self._run_query(
            prompt, session_id, hb_state
        )

        # Stop heartbeat
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # Log costs to DB
        if result.success and (result.cost_usd or result.input_tokens or result.output_tokens):
            try:
                await self._db.log_cost(
                    agent_name=agent.name,
                    session_id=result.session_id,
                    input_tokens=result.input_tokens or 0,
                    output_tokens=result.output_tokens or 0,
                    model=agent.config.model,
                )
            except Exception as e:
                logger.debug(f"Failed to log cost: {e}")

        # Build footer with session info
        footer_extra = None
        if result.session_id:
            sid = result.session_id[:8]
            parts = [f"session {sid}"]
            resume_cmd = agent.backend.terminal_resume_command(result.session_id)
            if resume_cmd:
                parts.append(f"`{resume_cmd}`")
            footer_extra = " │ ".join(parts)

        # Update placeholder with response or completion
        if result.success:
            # Post response text
            chunks = chunk_response(result.text)
            if chunks:
                try:
                    await self._poster.update(
                        channel=channel_id,
                        ts=placeholder_ts,
                        text=chunks[0],
                        agent_name=agent.name,
                        footer_extra=footer_extra,
                    )
                except Exception:
                    await self._poster.post(
                        channel=channel_id,
                        text=chunks[0],
                        thread_ts=reply_ts,
                        agent_name=agent.name,
                        footer_extra=footer_extra,
                    )

                # Overflow chunks as thread replies
                for chunk in chunks[1:]:
                    await self._poster.post(
                        channel=channel_id,
                        text=chunk,
                        thread_ts=reply_ts or placeholder_ts,
                        agent_name=agent.name,
                    )
        else:
            # Post error
            error_msg = f"❌ {agent.display_name} error: {result.error}"
            try:
                await self._poster.update(
                    channel=channel_id, ts=placeholder_ts, text=error_msg,
                    agent_name=agent.name,
                )
            except Exception:
                await self._poster.post(
                    channel=channel_id, text=error_msg, thread_ts=reply_ts,
                    agent_name=agent.name,
                )

        return result

    async def _run_query(
        self,
        prompt: str,
        session_id: str | None,
        hb_state: HeartbeatState,
    ) -> QueryResult:
        """Run the actual backend query, collecting events."""
        agent = self._agent
        response_parts: list[str] = []
        final_session_id = session_id or ""
        cost_usd = None
        input_tokens_count = None
        output_tokens_count = None

        try:
            async for event in agent.backend.query(
                session_id=session_id or "",
                prompt=prompt,
                allowed_tools=agent.profile.allowed_tools,
            ):
                if event.type == "text":
                    response_parts.append(event.content)
                elif event.type == "tool_use":
                    hb_state.record_tool(event.content, event.detail)
                elif event.type == "complete":
                    if event.detail:
                        final_session_id = event.detail
                    cost_usd = event.raw.get("cost_usd")
                    input_tokens_count = event.raw.get("input_tokens")
                    output_tokens_count = event.raw.get("output_tokens")
                elif event.type == "error":
                    return QueryResult(
                        text="",
                        session_id=final_session_id,
                        success=False,
                        error=event.content,
                        tool_count=hb_state.tool_count,
                    )

            return QueryResult(
                text="\n".join(response_parts),
                session_id=final_session_id,
                success=True,
                tool_count=hb_state.tool_count,
                cost_usd=cost_usd,
                input_tokens=input_tokens_count,
                output_tokens=output_tokens_count,
            )

        except Exception as e:
            logger.exception(f"Query failed: {e}")
            return QueryResult(
                text="",
                session_id=final_session_id,
                success=False,
                error=str(e),
                tool_count=hb_state.tool_count,
            )

    async def _heartbeat_loop(
        self,
        channel_id: str,
        placeholder_ts: str,
        thread_ts: str | None,
        hb_state: HeartbeatState,
        tip_rotator: TipRotator,
    ):
        """Continuously update the placeholder with heartbeat info."""
        agent = self._agent
        while True:
            await asyncio.sleep(self._heartbeat_interval)

            stalled = hb_state.is_stalled(self._stall_threshold)

            # Try to get context info from backend
            try:
                info = await agent.backend.get_session_info(agent.current_session_id or "")
                ctx_tokens = info.input_tokens
                ctx_limit = info.context_limit
            except Exception:
                ctx_tokens = None
                ctx_limit = None

            msg = format_heartbeat(
                agent_name=agent.name.capitalize(),
                host_id=agent.host_id,
                backend_name=agent.backend.name,
                elapsed_secs=hb_state.elapsed_secs(),
                tool_count=hb_state.tool_count,
                last_tool=hb_state.last_tool or "--",
                recent_tools=[t for t in hb_state.recent_tools],
                context_tokens=ctx_tokens,
                context_limit=ctx_limit,
                tip=tip_rotator.next(),
                stalled=stalled,
                stall_secs=hb_state.stall_secs() if stalled else 0,
            )

            try:
                await self._poster.update(
                    channel=channel_id, ts=placeholder_ts, text=msg,
                    agent_name=agent.name,
                )
            except Exception as e:
                logger.debug(f"Heartbeat update failed: {e}")
