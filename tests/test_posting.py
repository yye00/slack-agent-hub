import pytest
from unittest.mock import AsyncMock

from slack_io.posting import SlackPoster


@pytest.fixture
def poster():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ts": "1234.5678"})
    return SlackPoster(client=client, host_id="hotaisle", host_color="#4A90E2")


@pytest.mark.asyncio
async def test_post_includes_color_and_footer(poster):
    await poster.post(channel="C123", text="hello", agent_name="fred")
    call = poster._client.chat_postMessage.call_args
    attachments = call.kwargs["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["color"] == "#4A90E2"
    assert "fred@hotaisle" in attachments[0]["footer"]


@pytest.mark.asyncio
async def test_post_without_agent_name_uses_host(poster):
    await poster.post(channel="C123", text="system msg")
    call = poster._client.chat_postMessage.call_args
    footer = call.kwargs["attachments"][0]["footer"]
    assert footer == "hotaisle"


@pytest.mark.asyncio
async def test_post_with_footer_extra(poster):
    await poster.post(channel="C123", text="hi", agent_name="bob", footer_extra="claude")
    call = poster._client.chat_postMessage.call_args
    footer = call.kwargs["attachments"][0]["footer"]
    assert "bob@hotaisle" in footer
    assert "claude" in footer


@pytest.mark.asyncio
async def test_update_includes_color(poster):
    await poster.update(channel="C123", ts="1234.5678", text="updated", agent_name="fred")
    call = poster._client.chat_update.call_args
    attachments = call.kwargs["attachments"]
    assert attachments[0]["color"] == "#4A90E2"
    assert "fred@hotaisle" in attachments[0]["footer"]


@pytest.mark.asyncio
async def test_post_plain_has_no_attachments(poster):
    await poster.post_plain(channel="C123", text="plain")
    call = poster._client.chat_postMessage.call_args
    assert "attachments" not in call.kwargs
