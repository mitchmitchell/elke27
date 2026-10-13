"""Regression tests for arm/disarm PIN handling (0.3.9).

These go through the real ``generator_area_set_arm_state`` and the real
``Elke27Client._coerce_pin_for_generator``; only the transport is faked so the
outgoing payload can be inspected. In 0.3.8 every string PIN failed here because
the generator's postponed ``pin: int`` annotation was never recognized as ``int``.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from typing import Any, Literal, Union, cast

import pytest

from elke27_lib import client as client_mod
from elke27_lib import session as session_mod
from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import Elke27InvalidArgument
from elke27_lib.generators.registry import COMMANDS
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.internal import get_kernel, get_private


class _FakeSession:
    state = session_mod.SessionState.ACTIVE

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority, on_fail
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(0.0)


def _make_client() -> tuple[Elke27Client, _FakeSession]:
    client = Elke27Client()
    kernel = get_kernel(client)
    kernel.load_features_blocking()
    session = _FakeSession()
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    return client, session


async def _run_and_ack(
    client: Elke27Client,
    session: _FakeSession,
    call: Coroutine[Any, Any, Any],
) -> tuple[dict[str, Any], Any]:
    task = asyncio.ensure_future(call)
    client._event_loop = asyncio.get_running_loop()
    for _ in range(20):
        if session.sent or task.done():
            break
        await asyncio.sleep(0)
    if task.done():
        task.result()  # re-raise anything that failed before sending
    assert session.sent, "request was never sent to the panel"
    on_message = get_private(get_kernel(client), "_on_message")
    seen = 0
    while not task.done():
        await asyncio.sleep(0)
        while seen < len(session.sent):
            sent = session.sent[seen]
            if seen == 0:
                on_message(
                    {
                        "seq": sent["seq"],
                        "area": {"set_arm_state": {"error_code": E27ErrorCode.ELKERR_NONE}},
                    }
                )
            else:
                on_message(synthetic_success_reply(sent, sent_history=session.sent[:seen]))
            seen += 1
    sent = session.sent[0]
    return sent["area"]["set_arm_state"], await task


def _arm(client: Elke27Client, pin: Any) -> Coroutine[Any, Any, None]:
    return client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin=pin)


def _disarm(client: Elke27Client, pin: Any) -> Coroutine[Any, Any, None]:
    return client.async_disarm_area(1, pin=pin)


_ACTIONS = [
    pytest.param(_arm, "ARMED_AWAY", id="arm"),
    pytest.param(_disarm, "DISARMED", id="disarm"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "arm_state"), _ACTIONS)
@pytest.mark.parametrize(
    ("pin", "wire_pin"),
    [
        pytest.param("1234", 1234, id="string"),
        pytest.param("0123", 123, id="leading-zero"),
        pytest.param("000042", 42, id="six-digit-leading-zeros"),
        pytest.param(1234, 1234, id="int"),
    ],
)
async def test_arm_disarm_valid_pins_reach_panel_as_json_int(
    action: Callable[[Elke27Client, Any], Coroutine[Any, Any, None]],
    arm_state: str,
    pin: Any,
    wire_pin: int,
) -> None:
    client, session = _make_client()
    payload, result = await _run_and_ack(client, session, action(client, pin))
    assert result is None
    assert payload == {
        "area_id": 1,
        "arm_state": arm_state,
        "pin": wire_pin,
        "auto_stay_cancel": False,
        "exit_delay_cancel": False,
    }
    assert type(payload["pin"]) is int


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "arm_state"), _ACTIONS)
@pytest.mark.parametrize(
    "pin",
    [
        pytest.param("0000", id="all-zero"),
        pytest.param("12a4", id="non-digit"),
        pytest.param(" 1234", id="whitespace"),
        pytest.param("١٢٣٤", id="non-ascii-digits"),
        pytest.param("", id="empty"),
        pytest.param(None, id="none"),
        pytest.param(0, id="int-zero"),
        pytest.param(-5, id="int-negative"),
        pytest.param(True, id="bool"),
        pytest.param(12.0, id="float"),
    ],
)
async def test_arm_disarm_invalid_pins_rejected_before_send(
    action: Callable[[Elke27Client, Any], Coroutine[Any, Any, None]],
    arm_state: str,
    pin: Any,
) -> None:
    del arm_state
    client, session = _make_client()
    with pytest.raises(Elke27InvalidArgument):
        await action(client, pin)
    assert session.sent == []


@pytest.mark.asyncio
async def test_arm_with_disarmed_mode_routes_string_pin() -> None:
    client, session = _make_client()
    payload, _ = await _run_and_ack(
        client, session, client.async_arm_area(1, mode=ArmMode.DISARMED, pin="0123")
    )
    assert payload["arm_state"] == "DISARMED"
    assert payload["pin"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pin", "wire_pin"),
    [pytest.param("1234", 1234, id="string"), pytest.param("0123", 123, id="leading-zero")],
)
async def test_async_execute_coerces_string_pin_for_int_generator(pin: str, wire_pin: int) -> None:
    """Raw async_execute with a string PIN worked for neither arm nor disarm in 0.3.8."""
    client, session = _make_client()
    payload, result = await _run_and_ack(
        client,
        session,
        client.async_execute("area_set_arm_state", area_id=1, arm_state="ARMED_STAY", pin=pin),
    )
    assert result.ok is True
    assert payload["pin"] == wire_pin


def test_coerce_pin_resolves_postponed_annotations() -> None:
    area_spec = COMMANDS["area_set_arm_state"]
    zone_spec = COMMANDS["zone_set_status"]
    # The generator module uses postponed annotations, which broke 0.3.8.
    assert inspect.signature(area_spec.generator).parameters["pin"].annotation == "int"

    coerced = Elke27Client._coerce_pin_for_generator(  # pyright: ignore[reportPrivateUsage]
        area_spec, {"area_id": 1, "arm_state": "ARMED_AWAY", "pin": "0123"}
    )
    assert coerced["pin"] == 123
    # zone.set_status also takes an int PIN on the wire (0.3.10).
    coerced = Elke27Client._coerce_pin_for_generator(  # pyright: ignore[reportPrivateUsage]
        zone_spec, {"zone_id": 1, "pin": "0123", "bypassed": True}
    )
    assert coerced["pin"] == 123


@pytest.mark.parametrize(
    ("annotation", "wants_int"),
    [
        (int, True),
        ("int", True),
        ("int | str", False),
        ("str | int", False),
        (int | str, False),
        (str, False),
        ("str", False),
        (int | None, True),
        ("int | None", True),
        (inspect.Parameter.empty, False),
    ],
)
def test_generator_pin_wants_int_annotation_forms(annotation: object, wants_int: bool) -> None:
    def _gen(**_kwargs: Any) -> None:
        return None

    param = inspect.Parameter("pin", inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
    helper = cast(Any, client_mod)._generator_pin_wants_int
    assert helper(_gen, param) is wants_int


def test_generator_rejects_string_pin_with_value_error() -> None:
    generator = COMMANDS["area_set_arm_state"].generator
    with pytest.raises(ValueError):
        generator(area_id=1, arm_state="ARMED_AWAY", pin="1234")
    with pytest.raises(ValueError):
        generator(area_id=1, arm_state="ARMED_AWAY", pin=True)


def test_generator_pin_wants_int_edge_annotations() -> None:
    helper = cast(Any, client_mod)._generator_pin_wants_int
    kw = inspect.Parameter.KEYWORD_ONLY

    def _gen(**_kwargs: Any) -> None:
        return None

    # Unrecognized annotation forms are treated as "not int-only".
    literal = Literal[1234]
    assert helper(_gen, inspect.Parameter("pin", kw, annotation=literal)) is False
    assert helper(_gen, inspect.Parameter("pin", kw, annotation=Union[literal, int])) is False  # noqa: UP007

    # Unresolvable postponed annotations fall back to parsing the raw text.
    def _unresolvable(*, pin: NotDefinedAnywhere) -> None:  # type: ignore[name-defined] # noqa: F821 # pyright: ignore[reportUndefinedVariable]
        del pin

    pin_param = inspect.signature(_unresolvable).parameters["pin"]
    assert helper(_unresolvable, pin_param) is False
    int_param = inspect.Parameter("pin", kw, annotation="int")
    assert helper(_unresolvable, int_param) is True
