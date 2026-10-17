"""Raw API pass-through (decision 34): Elke27Client.async_raw_request."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest

from elke27_lib import Elke27CommandOutcomeUnknownError
from elke27_lib.client import Elke27Client
from elke27_lib.errors import (
    E27Error,
    Elke27InvalidArgument,
    Elke27PanelError,
    Elke27PermissionError,
)
from elke27_lib.kernel import E27Kernel, KernelError
from elke27_lib.linking import E27Identity, E27LinkKeys
from elke27_lib.states import AreaState
from test.helpers.internal import get_kernel, get_private
from test.test_transport_command_retry import _FakeSession

FAKE_PIN = 987654
FAKE_LINKKEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


class _Session(_FakeSession):
    class _Cfg:
        host = "test"
        port = 0

    cfg = _Cfg()


def _client(
    session: _FakeSession,
    *,
    enabled: bool = True,
    disarmed: bool = True,
    kernel: E27Kernel | None = None,
) -> Elke27Client:
    client = Elke27Client(enable_raw_passthrough=enabled, kernel=kernel)
    if kernel is None:
        kernel = get_kernel(client)
        cast(Any, kernel)._request_max_retries = 0
        cast(Any, kernel)._request_max_backoff_s = 0.0
    assert kernel is not None
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 4242
    cast(Any, kernel)._loop = asyncio.get_running_loop()
    kernel.state.areas[1] = AreaState(area_id=1, arm_state="DISARMED" if disarmed else "ARMED_AWAY")
    return client


async def _reply(client: Elke27Client, session: _FakeSession, build: Any) -> None:
    for _ in range(50):
        if session.sent:
            break
        await asyncio.sleep(0)
    sent = session.sent[-1]
    get_private(get_kernel(client), "_on_message")(build(sent))


@pytest.mark.asyncio
async def test_roundtrip_injects_seq_and_session() -> None:
    session = _Session()
    client = _client(session)
    task = asyncio.create_task(client.async_raw_request({"net_dev": {"get_list": {"block_id": 1}}}))
    await _reply(
        client,
        session,
        lambda s: {
            "seq": s["seq"],
            "session_id": 4242,
            "net_dev": {"get_list": {"error_code": 0, "block_count": 1, "net_devs": [1]}},
        },
    )
    result = await asyncio.wait_for(task, 2.0)
    sent = session.sent[0]
    assert isinstance(sent["seq"], int) and sent["seq"] > 0
    assert sent["session_id"] == 4242
    assert sent["net_dev"] == {"get_list": {"block_id": 1}}
    assert result.ok
    assert result.data == {
        "net_dev": {"get_list": {"error_code": 0, "block_count": 1, "net_devs": [1]}}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"seq": 5, "net_dev": {"get_list": {}}},
        {"session_id": 1, "net_dev": {"get_list": {}}},
        {"net_dev": {"get_list": {"seq": 9}}},
        {"net_dev": {"get_list": {}}, "zone": {"get_status": {}}},
        {"net_dev": {"get_list": {}, "get_attribs": {}}},
        {},
    ],
)
async def test_malformed_or_caller_seq_rejected_before_send(message: dict[str, Any]) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request(message, allow_installer=True)
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.asyncio
async def test_disabled_client_refuses() -> None:
    session = _Session()
    client = _client(session, enabled=False)
    result = await client.async_raw_request({"net_dev": {"get_list": {}}})
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"net_dev": {"del_attribs": {"net_dev_id": 3}}},
        {"made_up": {"thing": {}}},  # unknown routes fail closed
        {"net": {"dev_get_list": {}}},  # joins to net_dev_get_list
        {"area_get": {"status": {}}},  # joins to area_get_status
    ],
)
async def test_installer_or_unknown_route_needs_opt_in(message: dict[str, Any]) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request(message)
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
async def test_disarmed_route_refused_when_armed() -> None:
    session = _Session()
    client = _client(session, disarmed=False)
    result = await client.async_raw_request(
        {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True
    )
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
async def test_panel_error_code() -> None:
    session = _Session()
    client = _client(session)
    task = asyncio.create_task(
        client.async_raw_request(
            {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True
        )
    )
    await _reply(
        client,
        session,
        lambda s: {"seq": s["seq"], "net_dev": {"del_attribs": {"error_code": 11008}}},
    )
    result = await asyncio.wait_for(task, 2.0)
    assert isinstance(result.error, Elke27PanelError)
    assert result.error.panel_error_code == 11008


@pytest.mark.asyncio
async def test_sent_without_reply_is_outcome_unknown() -> None:
    session = _Session()
    client = _client(session)
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: 0.05
    result = await asyncio.wait_for(
        client.async_raw_request(
            {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True, timeout_s=0.02
        ),
        2.0,
    )
    assert isinstance(result.error, Elke27CommandOutcomeUnknownError)
    assert result.error.route == ("net_dev", "del_attribs")
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_disconnected_session_fails_without_send() -> None:
    session = _Session()
    client = _client(session)
    session.handle_disconnect(None)
    result = await client.async_raw_request({"net_dev": {"get_list": {}}})
    assert type(result.error) is E27Error
    assert "Session not active" in str(result.error)
    assert session.sent == []


@pytest.mark.asyncio
async def test_no_message_or_reply_content_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()
    client = _client(session)
    caplog.set_level(logging.DEBUG)
    task = asyncio.create_task(
        client.async_raw_request(
            {"net_dev": {"set_creds": {"net_dev_id": 7, "pin": FAKE_PIN, "linkkey": FAKE_LINKKEY}}},
            allow_installer=True,
        )
    )
    await _reply(
        client,
        session,
        lambda s: {
            "seq": s["seq"],
            "session_id": 4242,
            "net_dev": {"set_creds": {"error_code": 0, "linkkey": FAKE_LINKKEY, "pin": FAKE_PIN}},
        },
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert str(FAKE_PIN) not in text
    assert FAKE_LINKKEY not in text
    assert "net_dev_id" not in text
    summary = [r.getMessage() for r in caplog.records if "Raw pass-through" in r.getMessage()]
    assert len(summary) == 1
    assert "route=net_dev.set_creds outcome=ok" in summary[0]
    assert "allow_installer=True" in summary[0]


# --- wire hex suppression (Architect ruling 5) -----------------------------------
from types import SimpleNamespace  # noqa: E402

from elke27_lib import session as session_mod  # noqa: E402
from elke27_lib.session import SessionConfig  # noqa: E402
from test.test_session_extra import _ready_session  # noqa: E402

_FRAME = b"\x80\x05\x00\xde\xad\xbe\xef\x99"


def _wire_session() -> Any:
    sess = _ready_session()
    sess.cfg = SessionConfig(host="example", wire_log=True, auto_receive=False)
    sess.wire_log_suppress_seqs = {77}
    return sess


@pytest.mark.parametrize(
    ("obj", "dumped"),
    [
        ({"seq": 5, "zone": {"get_status": {}}}, True),
        ({"seq": 0, "authenticate": {"seq": 0, "pin": FAKE_PIN}}, False),  # plain
        ({"seq": 6, "session_id": 1, "control": {"authenticate": {"pin": FAKE_PIN}}}, False),
        ({"seq": 77, "net_dev": {"del_attribs": {"net_dev_id": 3}}}, False),  # raw seq
    ],
)
def test_tx_wire_hex_suppressed(
    caplog: pytest.LogCaptureFixture, obj: dict[str, Any], dumped: bool
) -> None:
    sess = _wire_session()
    caplog.set_level(logging.DEBUG)
    framed = sess._encode_json(obj)
    text = caplog.text
    assert ("TX framed" in text) is dumped
    assert (framed.hex() in text) is dumped


@pytest.mark.parametrize(
    ("payload", "dumped"),
    [
        (b'{"seq": 9, "zone": {}}', True),
        (b'{"authenticate": {"error_code": 0, "installer": true, "session_id": 5}}', False),
        (b'{"seq": 77, "net_dev": {"del_attribs": {"error_code": 0}}}', False),
    ],
)
def test_rx_wire_hex_suppressed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    payload: bytes,
    dumped: bool,
) -> None:
    sess = _wire_session()
    sess._recv_one_frame_no_crc = lambda **_k: _FRAME
    monkeypatch.setattr(
        session_mod,
        "decrypt_schema0_envelope",
        lambda **_k: SimpleNamespace(seq=1, payload=payload),
    )
    caplog.set_level(logging.DEBUG)
    sess.recv_json(timeout_s=0.0)
    assert (_FRAME.hex() in caplog.text) is dumped


def test_rx_raw_chunk_never_hex_dumped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sess = _wire_session()
    chunk = b"\x11\x22\x33\x44\x55\x66"
    monkeypatch.setattr(sess, "_recv_some", lambda *_a, **_k: chunk)
    monkeypatch.setattr(
        session_mod,
        "deframe_feed",
        lambda _s, _c: [SimpleNamespace(ok=True, frame_no_crc=_FRAME, error=None)],
    )
    caplog.set_level(logging.DEBUG)
    sess._recv_one_frame_no_crc(timeout_s=0.1)
    assert chunk.hex() not in caplog.text and _FRAME.hex() not in caplog.text


@pytest.mark.asyncio
async def test_kernel_shares_raw_seqs_with_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session built by connect() suppresses wire logs for the kernel's raw seqs."""
    created: list[Any] = []

    class _CapturingSession:
        def __init__(self, **_kw: Any) -> None:
            self.wire_log_suppress_seqs: Any = frozenset()
            created.append(self)

        def connect(self, *_a: Any, **_kw: Any) -> None:
            raise RuntimeError("stop after session setup")

    monkeypatch.setattr(session_mod, "Session", _CapturingSession)
    kernel = get_kernel(Elke27Client(enable_raw_passthrough=True))
    with pytest.raises(KernelError, match="stop after session setup"):
        await kernel.connect(
            E27LinkKeys(tempkey_hex="00" * 16, linkkey_hex="11" * 16, linkhmac_hex="22" * 20),
            client_identity=E27Identity(
                mn="222", sn="123456789012", fwver="1", hwver="1", osver="1"
            ),
            session_config=session_mod.SessionConfig(host="test", port=0),
        )
    assert created, "kernel.connect did not build a session"
    kernel.mark_raw_passthrough(123)
    assert 123 in created[0].wire_log_suppress_seqs


# --- leading-zero PIN (Architect ruling 7) ---------------------------------------
@pytest.mark.asyncio
async def test_authenticate_rejects_leading_zero_pin() -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_execute("control_authenticate", pin="0123")
    assert isinstance(result.error, Elke27InvalidArgument)
    assert "leading zero" in str(result.error)
    assert "0123" not in str(result.error)
    assert session.sent == []


# --- handler fan-out (Architect blocker A) ---------------------------------------
SENTINEL = "SENTINEL-7f3a9c"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "reply_body"),
    [
        (
            {"light": {"get_status": {"light_id": 1}}},
            {"light_id": 1, "error_code": 0, "name": SENTINEL, "status": SENTINEL},
        ),
        (
            {"zone": {"get_table_info": {}}},
            {"error_code": 0, "table_csm": SENTINEL, "table_elements": SENTINEL},
        ),
        (
            {"light": {"set_status": {"light_id": 1, "on": True}}},
            {"light_id": 1, "error_code": 0, "status": SENTINEL},
        ),
    ],
)
async def test_raw_reply_never_reaches_feature_handlers_or_logs(
    caplog: pytest.LogCaptureFixture, message: dict[str, Any], reply_body: dict[str, Any]
) -> None:
    session = _Session()
    client = _client(session)
    kernel = get_kernel(client)
    kernel.load_features_blocking(None)

    def domain_state() -> str:
        st = kernel.state
        return repr((st.areas, st.zones, st.lights, st.table_info_by_domain))

    before = domain_state()
    caplog.set_level(logging.DEBUG)
    domain = next(iter(message))
    verb = next(iter(message[domain]))
    task = asyncio.create_task(client.async_raw_request(message, allow_installer=True))
    await _reply(
        client,
        session,
        lambda s: {"seq": s["seq"], "session_id": 4242, domain: {verb: reply_body}},
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    assert result.data == {domain: {verb: reply_body}}
    assert all(SENTINEL not in r.getMessage() for r in caplog.records)
    assert SENTINEL not in caplog.text
    assert domain_state() == before  # raw replies do not update library state


@pytest.mark.asyncio
async def test_permission_keyed_by_exact_pair_no_collisions() -> None:
    from elke27_lib.client import raw_route_permission_table
    from elke27_lib.generators.registry import COMMANDS

    table = raw_route_permission_table()
    assert set(table) == {(spec.domain, spec.command) for spec in COMMANDS.values()}
    # Every other split of a known pair's joined name is an unknown route and
    # must be refused without allow_installer, whatever the known route's level.
    session = _Session()
    client = _client(session)
    checked = 0
    for domain, verb in table:
        joined = f"{domain}_{verb}"
        for i, ch in enumerate(joined):
            alt = (joined[:i], joined[i + 1 :])
            if ch != "_" or alt in table or not alt[0] or not alt[1]:
                continue
            result = await client.async_raw_request({alt[0]: {alt[1]: {}}})
            assert isinstance(result.error, Elke27PermissionError), alt
            checked += 1
    assert checked > 100
    assert session.sent == []


# --- in-flight seqs never evicted; no automatic retries (Bugbot HIGH, Codex P1) --
def test_inflight_raw_seq_survives_more_than_window() -> None:
    from elke27_lib.kernel import RawSeqTracker

    t = RawSeqTracker(late_window=4)
    t.mark(1)  # in flight the whole time
    for seq in range(2, 600):
        t.mark(seq)
        t.finish(seq)
    assert 1 in t  # never evicted while in flight
    assert 599 in t and 596 in t  # late window keeps the most recent finished
    assert 2 not in t  # old finished seqs age out
    t.finish(1)
    assert 1 in t  # now in the late window


@pytest.mark.asyncio
async def test_inflight_raw_request_keeps_protection_under_load(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _Session()
    client = _client(session)
    kernel = get_kernel(client)
    kernel.load_features_blocking(None)
    caplog.set_level(logging.DEBUG)
    task = asyncio.create_task(
        client.async_raw_request({"light": {"get_status": {"light_id": 1}}}, allow_installer=True)
    )
    for _ in range(50):
        if session.sent:
            break
        await asyncio.sleep(0)
    seq = session.sent[0]["seq"]
    for other in range(10_000, 10_400):  # > 256 other raw requests mark and finish
        kernel.mark_raw_passthrough(other)
        kernel.finish_raw_passthrough(other)
    get_private(kernel, "_on_message")(
        {"seq": seq, "light": {"get_status": {"light_id": 1, "error_code": 0, "name": SENTINEL}}}
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    assert SENTINEL not in caplog.text


@pytest.mark.asyncio
async def test_raw_get_is_never_resent_after_lost_reply() -> None:
    session = _Session()
    client = _client(session, kernel=E27Kernel(request_max_retries=3, request_max_backoff_s=0.0))
    result = await asyncio.wait_for(
        client.async_raw_request({"net_dev": {"get_list": {}}}, timeout_s=0.02), 2.0
    )
    await asyncio.sleep(0.1)
    assert isinstance(result.error, Elke27CommandOutcomeUnknownError)
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_normal_get_still_retries_after_lost_reply() -> None:
    """Control: the retry path exists for non-raw get_* (so the raw test is meaningful)."""
    session = _Session()
    client = _client(session, kernel=E27Kernel(request_max_retries=3, request_max_backoff_s=0.0))
    await asyncio.wait_for(client.async_execute("zone_get_status", zone_id=1, timeout_s=0.02), 2.0)
    assert len(session.sent) > 1


# --- non-mapping JSON verb values ------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        1,  # scalar int (net_dev.get_list block number)
        True,  # bool stays a JSON bool
        "abc",
        2.5,
        None,  # JSON null
        [1, "two", None, {"k": [False]}],  # list
    ],
)
async def test_non_mapping_value_sent_unchanged(value: Any) -> None:
    session = _Session()
    client = _client(session)
    task = asyncio.create_task(client.async_raw_request({"net_dev": {"get_list": value}}))
    await _reply(
        client,
        session,
        lambda s: {"seq": s["seq"], "net_dev": {"get_list": {"error_code": 0}}},
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    sent = session.sent[0]
    assert sent["net_dev"] == {"get_list": value}
    assert type(sent["net_dev"]["get_list"]) is type(value)
    assert sent["seq"] > 0 and sent["session_id"] == 4242


class _Obj:
    pass


class _IntSub(int):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        b"bytes",
        {1, 2},
        (1, 2),
        float("nan"),
        float("inf"),
        float("-inf"),
        _Obj(),
        _IntSub(3),  # int subclasses are not JSON ints
        [1, b"x"],  # nested bytes
        {"a": {1: "non-str key"}},
        [float("nan")],
    ],
)
async def test_non_json_value_rejected_before_send(value: Any) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request({"net_dev": {"get_list": value}}, allow_installer=True)
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.asyncio
async def test_rejection_error_never_echoes_value() -> None:
    session = _Session()
    client = _client(session)
    secret = b"987654-secret"
    result = await client.async_raw_request({"net_dev": {"get_list": [secret]}})
    assert isinstance(result.error, Elke27InvalidArgument)
    assert "987654" not in str(result.error)


@pytest.mark.asyncio
async def test_deeply_nested_value_rejected() -> None:
    session = _Session()
    client = _client(session)
    value: Any = 0
    for _ in range(100):
        value = [value]
    result = await client.async_raw_request({"net_dev": {"get_list": value}})
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [3, None, [3], True, "x"])
async def test_installer_verb_with_non_mapping_value_still_needs_opt_in(value: Any) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request({"net_dev": {"del_attribs": value}})
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []
    unknown = await client.async_raw_request({"made_up": {"thing": value}})
    assert isinstance(unknown.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
async def test_non_mapping_value_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()
    client = _client(session)
    caplog.set_level(logging.DEBUG)
    task = asyncio.create_task(
        client.async_raw_request(
            {"net_dev": {"set_creds": [FAKE_PIN, FAKE_LINKKEY]}}, allow_installer=True
        )
    )
    await _reply(
        client,
        session,
        lambda s: {"seq": s["seq"], "net_dev": {"set_creds": {"error_code": 0}}},
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert str(FAKE_PIN) not in text
    assert FAKE_LINKKEY not in text


@pytest.mark.parametrize("value", [1, None, [FAKE_PIN], "s3cret", True])
def test_tx_wire_hex_suppressed_for_non_mapping_raw_value(
    caplog: pytest.LogCaptureFixture, value: Any
) -> None:
    sess = _wire_session()
    caplog.set_level(logging.DEBUG)
    framed = sess._encode_json({"seq": 77, "net_dev": {"get_list": value}})
    assert "TX framed" not in caplog.text
    assert framed.hex() not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        "\ud800",  # unpaired surrogate: not UTF-8 encodable
        {"k\udfff": 1},  # in a key
        [10**5000],  # past the int-to-str digit limit
    ],
)
async def test_unencodable_json_value_rejected_before_send(value: Any) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request({"net_dev": {"get_list": value}})
    assert isinstance(result.error, Elke27InvalidArgument)
    assert "encode" in str(result.error)
    assert session.sent == []


@pytest.mark.asyncio
async def test_non_dict_mapping_payload_still_sent() -> None:
    """A top-level MappingProxyType passes the encode check (Bugbot, #63)."""
    from types import MappingProxyType

    session = _Session()
    client = _client(session)
    task = asyncio.create_task(
        client.async_raw_request({"net_dev": {"get_list": MappingProxyType({"block_id": 1})}})
    )
    await _reply(
        client, session, lambda s: {"seq": s["seq"], "net_dev": {"get_list": {"error_code": 0}}}
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    assert session.sent[0]["net_dev"] == {"get_list": {"block_id": 1}}
