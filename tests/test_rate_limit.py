"""Tests for token bucket rate limiter."""

from __future__ import annotations

import sys
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.rate_limit import RateLimiter
from core.config import RateLimitConfig

# Stub out slack_bolt so hub.py can be imported without the real package
for _mod in [
    "slack_bolt",
    "slack_bolt.async_app",
    "slack_bolt.adapter",
    "slack_bolt.adapter.socket_mode",
    "slack_bolt.adapter.socket_mode.aiohttp",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ── RateLimiter unit tests ─────────────────────────────────────────────────────

class TestRateLimiterBasics:
    def test_allow_within_limit(self):
        """Requests within token budget should be allowed."""
        rl = RateLimiter(max_tokens=5, refill_per_sec=0.0)
        for _ in range(5):
            assert rl.allow("user1") is True

    def test_deny_when_tokens_exhausted(self):
        """Once tokens are exhausted, further requests should be denied."""
        rl = RateLimiter(max_tokens=3, refill_per_sec=0.0)
        for _ in range(3):
            rl.allow("user1")
        assert rl.allow("user1") is False

    def test_disabled_when_max_tokens_zero(self):
        """max_tokens=0 disables rate limiting — always allows."""
        rl = RateLimiter(max_tokens=0, refill_per_sec=1.0)
        for _ in range(1000):
            assert rl.allow("user1") is True

    def test_remaining_decrements_on_allow(self):
        """remaining() should decrease as tokens are consumed."""
        rl = RateLimiter(max_tokens=5, refill_per_sec=0.0)
        assert rl.remaining("user1") == 5
        rl.allow("user1")
        assert rl.remaining("user1") == 4
        rl.allow("user1")
        assert rl.remaining("user1") == 3

    def test_remaining_zero_when_exhausted(self):
        """remaining() should return 0 when bucket is empty."""
        rl = RateLimiter(max_tokens=2, refill_per_sec=0.0)
        rl.allow("user1")
        rl.allow("user1")
        assert rl.remaining("user1") == 0

    def test_remaining_disabled_returns_999(self):
        """When disabled (max_tokens=0), remaining() returns 999."""
        rl = RateLimiter(max_tokens=0, refill_per_sec=1.0)
        assert rl.remaining("user1") == 999

    def test_new_user_starts_full(self):
        """A new user should start with a full bucket."""
        rl = RateLimiter(max_tokens=10, refill_per_sec=0.0)
        assert rl.remaining("brand_new_user") == 10


class TestRateLimiterPerUser:
    def test_separate_buckets_per_user(self):
        """Each user has an independent token bucket."""
        rl = RateLimiter(max_tokens=2, refill_per_sec=0.0)
        rl.allow("alice")
        rl.allow("alice")
        # alice is exhausted
        assert rl.allow("alice") is False
        # bob should still have full bucket
        assert rl.allow("bob") is True
        assert rl.allow("bob") is True

    def test_multiple_users_independent(self):
        """Exhausting one user's bucket does not affect another."""
        rl = RateLimiter(max_tokens=3, refill_per_sec=0.0)
        for _ in range(3):
            rl.allow("user_a")
        assert rl.remaining("user_a") == 0
        assert rl.remaining("user_b") == 3


class TestRateLimiterRefill:
    def test_tokens_refill_over_time(self):
        """Tokens should be refilled as time passes."""
        rl = RateLimiter(max_tokens=5, refill_per_sec=10.0)
        # Exhaust all tokens
        for _ in range(5):
            rl.allow("user1")
        assert rl.remaining("user1") == 0

        # Simulate time passing by manipulating the bucket's last_refill
        bucket = rl._get_bucket("user1")
        bucket["last_refill"] -= 1.0  # pretend 1 second has passed
        # Should have gotten 10 tokens back but capped at max (5)
        assert rl.remaining("user1") == 5

    def test_refill_does_not_exceed_max(self):
        """Refilled tokens should never exceed max_tokens."""
        rl = RateLimiter(max_tokens=5, refill_per_sec=100.0)
        # Use 1 token
        rl.allow("user1")
        bucket = rl._get_bucket("user1")
        # Simulate 10 seconds passing (would refill 1000 tokens without cap)
        bucket["last_refill"] -= 10.0
        assert rl.remaining("user1") == 5  # capped at max

    def test_partial_refill(self):
        """Partial refill should allow previously-denied requests."""
        rl = RateLimiter(max_tokens=2, refill_per_sec=2.0)
        # Exhaust tokens
        rl.allow("user1")
        rl.allow("user1")
        assert rl.allow("user1") is False

        # Simulate 0.6 seconds passing — should refill 1.2 tokens
        bucket = rl._get_bucket("user1")
        bucket["last_refill"] -= 0.6
        # Now should have ~1.2 tokens => floor to 1 => allow 1 more
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False  # not enough for second


class TestRateLimitConfig:
    def test_default_values(self):
        """RateLimitConfig should have sensible defaults."""
        cfg = RateLimitConfig()
        assert cfg.max_queries_per_user == 10
        assert cfg.refill_per_sec == 0.5

    def test_custom_values(self):
        """RateLimitConfig should accept custom values."""
        cfg = RateLimitConfig(max_queries_per_user=20, refill_per_sec=1.0)
        assert cfg.max_queries_per_user == 20
        assert cfg.refill_per_sec == 1.0

    def test_disabled_with_zero(self):
        """max_queries_per_user=0 means disabled."""
        cfg = RateLimitConfig(max_queries_per_user=0)
        rl = RateLimiter(max_tokens=cfg.max_queries_per_user, refill_per_sec=cfg.refill_per_sec)
        assert rl.allow("anyone") is True


class TestHubConfigRateLimit:
    def test_hub_config_has_rate_limit_field(self):
        """HubConfig should include a rate_limit field with a RateLimitConfig."""
        from core.config import HubConfig, RateLimitConfig, PermissionsConfig, HeartbeatConfig, MonitorConfig, TranscriptConfig
        cfg = HubConfig(
            host_id="test",
            host_name="test",
            backends={},
            agents={},
            profiles={},
            ops_channel="C_OPS",
            registry_channel="C_REG",
            heartbeat=HeartbeatConfig(),
            monitors=MonitorConfig(),
            transcript=TranscriptConfig(),
            permissions=PermissionsConfig(),
            rate_limit=RateLimitConfig(),
        )
        assert isinstance(cfg.rate_limit, RateLimitConfig)
        assert cfg.rate_limit.max_queries_per_user == 10

    def test_hub_config_rate_limit_default(self):
        """HubConfig.rate_limit should have a default so old configs still work."""
        from core.config import HubConfig, PermissionsConfig, HeartbeatConfig, MonitorConfig, TranscriptConfig
        # Should not raise even without specifying rate_limit
        cfg = HubConfig(
            host_id="test",
            host_name="test",
            backends={},
            agents={},
            profiles={},
            ops_channel="C_OPS",
            registry_channel="C_REG",
            heartbeat=HeartbeatConfig(),
            monitors=MonitorConfig(),
            transcript=TranscriptConfig(),
            permissions=PermissionsConfig(),
        )
        assert cfg.rate_limit.max_queries_per_user == 10


# ── hub.py integration: rate limiter wired into handle_message ─────────────────

@pytest.mark.asyncio
async def test_rate_limit_blocks_agent_query_when_exhausted():
    """When rate limiter is exhausted for a user, AGENT_QUERY should be blocked."""
    import hub

    rl = RateLimiter(max_tokens=1, refill_per_sec=0.0)
    rl.allow("UUSER")  # exhaust the single token

    poster = MagicMock()
    poster.post = AsyncMock()

    original_rl = hub.rate_limiter
    original_poster = hub.poster
    try:
        hub.rate_limiter = rl
        hub.poster = poster
        hub._shutting_down = False
        hub._selftest_passed = True

        from core.router import RouteAction, RouteResult
        from core.commands import ParsedCommand

        mock_result = MagicMock()
        mock_result.action = RouteAction.AGENT_QUERY
        mock_result.target_agent = "agent1"

        with patch.object(hub, "router") as mock_router:
            mock_router.route.return_value = mock_result
            event = {"text": "hello", "channel": "C123", "user": "UUSER"}
            await hub.handle_message(event, say=AsyncMock())

        # Should have posted rate limit message
        poster.post.assert_called_once()
        call_kwargs = poster.post.call_args
        kwargs = call_kwargs.kwargs if hasattr(call_kwargs, 'kwargs') else call_kwargs[1]
        assert "rate limit" in kwargs["text"].lower() or "Rate limit" in kwargs["text"]
    finally:
        hub.rate_limiter = original_rl
        hub.poster = original_poster


@pytest.mark.asyncio
async def test_rate_limit_allows_agent_query_when_tokens_available():
    """When tokens are available, AGENT_QUERY should proceed normally."""
    import hub

    rl = RateLimiter(max_tokens=5, refill_per_sec=0.0)

    poster = MagicMock()
    poster.post = AsyncMock()

    original_rl = hub.rate_limiter
    original_poster = hub.poster
    original_agents = hub.agents
    try:
        hub.rate_limiter = rl
        hub.poster = poster
        hub._shutting_down = False
        hub._selftest_passed = True
        hub.agents = {}  # no agents, so run_agent_query won't be called

        from core.router import RouteAction

        mock_result = MagicMock()
        mock_result.action = RouteAction.AGENT_QUERY
        mock_result.target_agent = "nonexistent_agent"

        with patch.object(hub, "router") as mock_router:
            mock_router.route.return_value = mock_result
            event = {"text": "hello", "channel": "C123", "user": "UUSER"}
            await hub.handle_message(event, say=AsyncMock())

        # Should NOT have posted a rate limit message (agent just not found)
        poster.post.assert_not_called()
        # Token should have been consumed
        assert rl.remaining("UUSER") == 4
    finally:
        hub.rate_limiter = original_rl
        hub.poster = original_poster
        hub.agents = original_agents


@pytest.mark.asyncio
async def test_rate_limit_not_applied_to_commands():
    """Commands should not be rate-limited (they're cheap)."""
    import hub

    rl = RateLimiter(max_tokens=0, refill_per_sec=0.0)  # effectively disabled

    poster = MagicMock()
    poster.post = AsyncMock()
    command_handler = MagicMock()
    command_handler.handle = AsyncMock()

    original_rl = hub.rate_limiter
    original_poster = hub.poster
    original_ch = hub.command_handler
    original_pc = hub.permission_checker
    try:
        hub.rate_limiter = rl
        hub.poster = poster
        hub.command_handler = command_handler
        hub.permission_checker = None  # no permission checks
        hub._shutting_down = False
        hub._selftest_passed = True

        from core.router import RouteAction
        from core.commands import ParsedCommand

        mock_parsed = MagicMock()
        mock_parsed.command = "agents"
        mock_parsed.args = []
        mock_parsed.options = {}

        mock_result = MagicMock()
        mock_result.action = RouteAction.COMMAND
        mock_result.parsed = mock_parsed
        mock_result.target_agent = None

        with patch.object(hub, "router") as mock_router, \
             patch.object(hub, "db") as mock_db:
            mock_router.route.return_value = mock_result
            mock_db.log_audit = AsyncMock()
            event = {"text": "!agents", "channel": "C123", "user": "UUSER"}
            await hub.handle_message(event, say=AsyncMock())

        # Command should have been handled (no rate limit message)
        command_handler.handle.assert_called_once()
    finally:
        hub.rate_limiter = original_rl
        hub.poster = original_poster
        hub.command_handler = original_ch
        hub.permission_checker = original_pc
