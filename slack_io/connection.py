"""Slack Socket Mode connection setup."""

import os

from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp


def create_app() -> AsyncApp:
    """Create Slack Bolt async app."""
    return AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])


def create_socket_handler(app: AsyncApp) -> AsyncSocketModeHandler:
    """Create Socket Mode handler for the app."""
    return AsyncSocketModeHandler(
        app=app, app_token=os.environ["SLACK_APP_TOKEN"]
    )
