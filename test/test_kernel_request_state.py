import asyncio
import unittest
from collections.abc import Callable, Mapping
from typing import Any

from typing_extensions import override

from elke27_lib import kernel as kernel_mod
from elke27_lib.errors import ConnectionLost, E27Timeout
from elke27_lib.kernel import E27Kernel


class FakeSession:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(
        self,
        obj: dict[str, Any],
        *,
        priority: object,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        _ = priority, on_fail
        self.sent.append(obj)
        if on_sent is not None:
            on_sent(0.0)


class KernelRequestStateTests(unittest.IsolatedAsyncioTestCase):
    kernel: E27Kernel | None = None
    fake_session: FakeSession | None = None

    @override
    async def asyncSetUp(self) -> None:
        self.kernel = E27Kernel(request_timeout_s=0.05)
        self.fake_session = FakeSession()
        setattr(self.kernel, "_session", self.fake_session)
        setattr(self.kernel, "_loop", asyncio.get_running_loop())

    def _get_kernel(self) -> E27Kernel:
        kernel = self.kernel
        assert kernel is not None
        return kernel

    def _get_session(self) -> FakeSession:
        session = self.fake_session
        assert session is not None
        return session

    def _create_pending(self, seq: int) -> asyncio.Future[Mapping[str, Any]]:
        kernel = self._get_kernel()
        return kernel.pending_responses.create(
            seq,
            command_key="test",
            expected_route=("system", "ping"),
            loop=asyncio.get_running_loop(),
        )

    def _send_request(self, seq: int, *, timeout_s: float = 0.05) -> None:
        kernel = self._get_kernel()
        kernel.send_request_with_seq(
            seq,
            "system",
            "ping",
            {"x": 1},
            pending=False,
            opaque=None,
            expected_route=("system", "ping"),
            timeout_s=timeout_s,
        )

    async def test_normal_reply_path(self) -> None:
        kernel = self._get_kernel()
        session = self._get_session()
        seq = 101
        future = self._create_pending(seq)
        self._send_request(seq)
        await asyncio.sleep(0)
        self.assertEqual(len(session.sent), 1)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IN_FLIGHT)

        msg = {"seq": seq, "system": {"ping": {"ok": True}}}
        getattr(kernel, "_on_message")(msg)
        reply = await asyncio.wait_for(future, timeout=0.1)
        self.assertEqual(reply, msg)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IDLE)
        self.assertIsNone(getattr(kernel, "_active_seq"))

    async def test_timeout_path(self) -> None:
        kernel = self._get_kernel()
        seq = 102
        future = self._create_pending(seq)
        self._send_request(seq, timeout_s=0.02)
        await asyncio.sleep(0.05)
        with self.assertRaises(E27Timeout):
            await asyncio.wait_for(future, timeout=0.1)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IDLE)

    async def test_reply_then_timeout_race(self) -> None:
        kernel = self._get_kernel()
        seq = 103
        future = self._create_pending(seq)
        self._send_request(seq, timeout_s=0.5)
        await asyncio.sleep(0)

        msg = {"seq": seq, "system": {"ping": {"ok": True}}}
        getattr(kernel, "_on_message")(msg)
        getattr(kernel, "_on_reply_timeout")(seq)
        reply = await asyncio.wait_for(future, timeout=0.1)
        self.assertEqual(reply, msg)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IDLE)
        self.assertIsNone(getattr(kernel, "_active_seq"))

    async def test_late_reply_after_timeout(self) -> None:
        kernel = self._get_kernel()
        seq = 104
        future = self._create_pending(seq)
        self._send_request(seq, timeout_s=0.5)
        await asyncio.sleep(0)

        getattr(kernel, "_on_reply_timeout")(seq)
        with self.assertRaises(E27Timeout):
            await asyncio.wait_for(future, timeout=0.1)

        msg = {"seq": seq, "system": {"ping": {"ok": True}}}
        getattr(kernel, "_on_message")(msg)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IDLE)
        self.assertIsNone(getattr(kernel, "_active_seq"))

    async def test_disconnect_while_in_flight(self) -> None:
        kernel = self._get_kernel()
        seq = 105
        future = self._create_pending(seq)
        self._send_request(seq, timeout_s=0.5)
        await asyncio.sleep(0)

        getattr(kernel, "_abort_requests")(ConnectionLost("Session disconnected."))
        with self.assertRaises(ConnectionLost):
            await asyncio.wait_for(future, timeout=0.1)
        request_state = getattr(kernel_mod, "_RequestState")
        self.assertEqual(getattr(kernel, "_request_state"), request_state.IDLE)

    async def test_no_concurrent_sends(self) -> None:
        kernel = self._get_kernel()
        session = self._get_session()
        seq1 = 106
        seq2 = 107
        future1 = self._create_pending(seq1)
        future2 = self._create_pending(seq2)
        self._send_request(seq1, timeout_s=0.5)
        self._send_request(seq2, timeout_s=0.5)
        await asyncio.sleep(0)

        self.assertEqual(len(session.sent), 1)
        getattr(kernel, "_on_message")({"seq": seq1, "system": {"ping": {"ok": True}}})
        await asyncio.wait_for(future1, timeout=0.1)
        await asyncio.sleep(0)
        self.assertEqual(len(session.sent), 2)
        getattr(kernel, "_on_message")({"seq": seq2, "system": {"ping": {"ok": True}}})
        await asyncio.wait_for(future2, timeout=0.1)


def test_bootstrap_requests_zone_defs() -> None:
    kernel = E27Kernel()
    setattr(kernel, "_session", object())
    recorded: list[tuple[tuple[str, str], dict[str, object]]] = []

    def _fake_request(route: tuple[str, str], **kwargs: object) -> None:
        recorded.append((route, dict(kwargs)))

    setattr(kernel, "request", _fake_request)
    for route in (
        ("area", "get_table_info"),
        ("zone", "get_table_info"),
        ("output", "get_table_info"),
        ("tstat", "get_table_info"),
        ("area", "get_configured"),
        ("zone", "get_configured"),
        ("output", "get_configured"),
        ("user", "get_configured"),
        ("zone", "get_defs"),
    ):
        def _empty_payload(**_kwargs: object) -> dict[str, Any]:
            return {}

        kernel.requests.register(route, _empty_payload)

    getattr(kernel, "_bootstrap_requests")()
    assert ("zone", "get_defs") in [route for route, _ in recorded]
