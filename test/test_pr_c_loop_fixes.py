from __future__ import annotations

import inspect
import threading
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from elke27_lib import discovery, linking_thread
from elke27_lib.client import Elke27Client
from elke27_lib.kernel_loop import E27Kernel
from elke27_lib.pending_loop import PendingResponseManager

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_kernel_link_tcp_path_runs_off_asyncio_loop_thread() -> None:
    captured: dict[str, threading.Thread] = {}

    def _fake_do_tcp_api_link(*_a: object, **_k: object) -> linking_thread.E27LinkKeys:
        captured["worker"] = threading.current_thread()
        return linking_thread.E27LinkKeys(
            tempkey_hex="0" * 32,
            linkkey_hex="0" * 32,
            linkhmac_hex="0" * 40,
        )

    panel: dict[str, Any] = {"host": "127.0.0.1", "port": 1}
    identity = linking_thread.E27Identity(
        mn="222", sn="000000001", fwver="0.1", hwver="0.1", osver="0.1"
    )
    creds = type("C", (), {"access_code": "1", "passphrase": "2"})

    kernel = E27Kernel()
    with mock.patch.object(linking_thread, "do_tcp_api_link", _fake_do_tcp_api_link):
        await kernel.link(panel, identity, creds)

    assert "worker" in captured
    assert captured["worker"] is not threading.main_thread()
    assert threading.current_thread() is threading.main_thread()


def test_session_marshals_callbacks_with_call_soon_threadsafe() -> None:
    session_text = (_REPO_ROOT / "src" / "elke27_lib" / "session_thread.py").read_text(
        encoding="utf-8"
    )
    assert "call_soon_threadsafe" in session_text
    assert "def _invoke_on_loop" in session_text


def test_pending_loop_uses_acquire_timeout_on_shared_lock() -> None:
    pending_text = (_REPO_ROOT / "src" / "elke27_lib" / "pending_loop.py").read_text(
        encoding="utf-8"
    )
    assert pending_text.count("acquire(timeout=") >= 5


@pytest.mark.parametrize(
    ("obj", "method"),
    [
        (PendingResponseManager(), "create"),
        (PendingResponseManager(), "drop"),
        (PendingResponseManager(), "pending_count"),
        (PendingResponseManager(), "fail_all"),
        (Elke27Client(kernel=E27Kernel()), "subscribe"),
        (Elke27Client(kernel=E27Kernel()), "unsubscribe"),
        (Elke27Client(kernel=E27Kernel()), "subscribe_typed"),
        (Elke27Client(kernel=E27Kernel()), "unsubscribe_typed"),
        (E27Kernel(), "load_features_blocking"),
    ],
)
def test_lock_uses_acquire_timeout(obj: object, method: str) -> None:
    fn = getattr(obj, method)
    assert "acquire(timeout=" in inspect.getsource(fn)


def test_discovery_async_scan_uses_executor_for_udp_socket() -> None:
    assert "asyncio.to_thread" in inspect.getsource(discovery.AIOELKDiscovery.async_scan)
