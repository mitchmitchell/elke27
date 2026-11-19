"""Futures nobody awaits any more still have their failure retrieved.

A failed future that is collected before anyone reads its exception makes asyncio
log "Future exception was never retrieved", and that log lands in whichever test
happens to trigger the collection.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from elke27_lib.client import Elke27DisconnectedError
from elke27_lib.errors import E27Timeout
from test.helpers.internal import (
    client_with_fake_session,
    close_while_keepalive_probe_waits_to_send,
    release_reply_publication_failed_by_disconnect,
    reply_publication_seq_active,
    time_out_command,
    unretrieved_future_errors,
)


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_timed_out_command_reply_failure_is_retrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The kernel fails the reply future on a later loop turn, after async_execute
    has given up on it."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    client = client_with_fake_session()
    result = await time_out_command(client, "control_get_version_info")
    assert result.ok is False
    assert isinstance(result.error, E27Timeout)
    await _settle()
    assert unretrieved_future_errors(caplog.records) == []


@pytest.mark.asyncio
async def test_keepalive_probe_failed_by_close_is_retrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """close() cancels the keepalive task while its probe waits to be sent, then
    fails every pending reply future, the probe's included."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    client = client_with_fake_session()
    await close_while_keepalive_probe_waits_to_send(client)
    await _settle()
    assert unretrieved_future_errors(caplog.records) == []


@pytest.mark.asyncio
async def test_released_publication_failed_by_disconnect_is_retrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A disconnect fails every publication waiter, including one whose command
    no longer waits on publication; releasing that command reads the failure."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    client = client_with_fake_session()
    release_reply_publication_failed_by_disconnect(
        client,
        41,
        Elke27DisconnectedError("Connection lost while waiting for snapshot publication."),
    )
    assert not reply_publication_seq_active(client, 41)
    assert unretrieved_future_errors(caplog.records) == []
