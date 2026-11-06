"""Async pending response manager keyed by seq."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

ResponseKey = tuple[str, str]
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingResponse:
    seq: int
    command_key: str
    expected_route: ResponseKey
    created_at: float
    future: asyncio.Future[Mapping[str, Any]]
    loop: asyncio.AbstractEventLoop


class PendingResponseManager:
    _now: Callable[[], float]
    _pending: dict[int, PendingResponse]
    _lock: threading.Lock

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._pending = {}
        self._lock = threading.Lock()

    def create(
        self,
        seq: int,
        *,
        command_key: str,
        expected_route: ResponseKey,
        loop: asyncio.AbstractEventLoop,
    ) -> asyncio.Future[Mapping[str, Any]]:
        future: asyncio.Future[Mapping[str, Any]] = loop.create_future()
        entry = PendingResponse(
            seq=seq,
            command_key=command_key,
            expected_route=expected_route,
            created_at=self._now(),
            future=future,
            loop=loop,
        )
        if not self._lock.acquire(timeout=30.0):
            raise RuntimeError("Pending response lock contention timed out.")
        try:
            self._pending[seq] = entry
        finally:
            self._lock.release()
        return future

    def resolve(self, seq: int, msg: Mapping[str, Any]) -> bool:
        entry = self._pop(seq)
        if entry is None:
            return False

        def _set_result() -> None:
            if not entry.future.done():
                entry.future.set_result(msg)

        self._call_in_loop(entry, _set_result)
        return True

    def fail(self, seq: int, exc: BaseException) -> bool:
        entry = self._pop(seq)
        if entry is None:
            return False

        def _set_exc() -> None:
            if not entry.future.done():
                entry.future.set_exception(exc)

        self._call_in_loop(entry, _set_exc)
        return True

    def drop(self, seq: int) -> None:
        if not self._lock.acquire(timeout=30.0):
            return
        try:
            self._pending.pop(seq, None)
        finally:
            self._lock.release()

    def pending_count(self) -> int:
        if not self._lock.acquire(timeout=30.0):
            return 0
        try:
            return len(self._pending)
        finally:
            self._lock.release()

    def fail_all(self, exc: BaseException) -> None:
        if not self._lock.acquire(timeout=30.0):
            raise RuntimeError("Pending response lock contention timed out.")
        try:
            entries = list(self._pending.values())
            self._pending.clear()
        finally:
            self._lock.release()
        for entry in entries:

            def _set_exc(entry: PendingResponse = entry) -> None:
                if not entry.future.done():
                    entry.future.set_exception(exc)

            self._call_in_loop(entry, _set_exc)

    def _pop(self, seq: int) -> PendingResponse | None:
        if not self._lock.acquire(timeout=30.0):
            return None
        try:
            return self._pending.pop(seq, None)
        finally:
            self._lock.release()

    @staticmethod
    def _call_in_loop(entry: PendingResponse, fn: Callable[[], None]) -> None:
        try:
            entry.loop.call_soon_threadsafe(fn)
        except RuntimeError as exc:
            LOG.warning("PendingResponse loop dispatch failed: %s", exc, exc_info=True)
            fn()
