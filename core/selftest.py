"""Startup self-test — verify dependencies before accepting messages."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_io.posting import SlackPoster

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a single self-test check."""
    name: str
    passed: bool
    detail: str = ""
    critical: bool = False


class StartupSelfTest:
    """Runs startup checks and reports results to ops channel."""

    def __init__(
        self,
        slack_client: AsyncWebClient,
        poster: SlackPoster,
        ops_channel_id: str,
    ):
        self._slack = slack_client
        self._poster = poster
        self._ops_channel_id = ops_channel_id

    async def run_checks(
        self,
        channel_ids: list[str],
        backend_names: list[str],
    ) -> list[CheckResult]:
        """Run all self-test checks and return results."""
        results: list[CheckResult] = []

        # 1. Slack API connectivity
        results.append(await self._check_slack_api())

        # 2. Ops channel writable
        results.append(await self._check_ops_channel())

        # 3. Configured channels exist
        for ch_id in channel_ids:
            results.append(await self._check_channel(ch_id))

        # 4. Backend CLIs reachable
        for name in backend_names:
            results.append(self._check_backend(name))

        # 5. files:write scope (non-critical, Issue #4)
        results.append(await self._check_files_write())

        return results

    async def run_and_report(
        self,
        channel_ids: list[str],
        backend_names: list[str],
    ) -> bool:
        """Run checks, post results to ops, return True if no critical failures."""
        results = await self.run_checks(channel_ids, backend_names)

        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        critical_failed = [r for r in failed if r.critical]

        lines = ["*Startup self-test results:*", ""]
        for r in results:
            icon = "\u2705" if r.passed else "\u274c"
            detail = f" \u2014 {r.detail}" if r.detail else ""
            crit = " *(critical)*" if r.critical and not r.passed else ""
            lines.append(f"{icon} {r.name}{detail}{crit}")

        lines.append("")
        lines.append(f"{len(passed)} passed, {len(failed)} failed")

        if critical_failed:
            lines.append("\u26d4 Critical failures \u2014 hub will not accept messages")

        text = "\n".join(lines)

        try:
            await self._poster.post(
                channel=self._ops_channel_id,
                text=text,
            )
        except Exception as e:
            logger.error(f"Failed to post self-test results: {e}")

        return len(critical_failed) == 0

    async def _check_slack_api(self) -> CheckResult:
        try:
            resp = await self._slack.auth_test()
            team = resp.get("team", "unknown")
            return CheckResult(
                name="slack_api",
                passed=True,
                detail=f"connected to {team}",
                critical=True,
            )
        except Exception as e:
            return CheckResult(
                name="slack_api",
                passed=False,
                detail=str(e),
                critical=True,
            )

    async def _check_ops_channel(self) -> CheckResult:
        try:
            await self._slack.conversations_info(channel=self._ops_channel_id)
            return CheckResult(
                name="ops_channel",
                passed=True,
                detail=self._ops_channel_id,
                critical=True,
            )
        except Exception as e:
            return CheckResult(
                name="ops_channel",
                passed=False,
                detail=str(e),
                critical=True,
            )

    async def _check_channel(self, channel_id: str) -> CheckResult:
        try:
            await self._slack.conversations_info(channel=channel_id)
            return CheckResult(
                name=f"channel:{channel_id}",
                passed=True,
            )
        except Exception as e:
            return CheckResult(
                name=f"channel:{channel_id}",
                passed=False,
                detail=str(e),
            )

    def _check_backend(self, name: str) -> CheckResult:
        """Check if a backend CLI is available on PATH."""
        cli_name = name
        found = shutil.which(cli_name) is not None
        return CheckResult(
            name=f"backend:{name}",
            passed=found,
            detail=f"{'found' if found else 'not found'} on PATH",
            critical=True,
        )

    async def _check_files_write(self) -> CheckResult:
        """Check files:write scope by attempting a minimal file upload.

        This is a non-critical check — file upload is optional functionality.
        Uses files.getUploadURLExternal which requires files:write scope.
        """
        try:
            await self._slack.files_getUploadURLExternal(
                filename="selftest.txt", length=1
            )
            return CheckResult(
                name="files_write_scope",
                passed=True,
                detail="files:write scope available",
            )
        except Exception as e:
            return CheckResult(
                name="files_write_scope",
                passed=False,
                detail=f"files:write scope missing or unavailable: {e}",
            )
