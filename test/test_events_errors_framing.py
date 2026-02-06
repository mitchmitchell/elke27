from __future__ import annotations

import logging

import pytest

from elke27_lib import errors, events, framing


def test_event_domain_property() -> None:
    ev = events.Event(
        kind="k",
        at=0.0,
        seq=None,
        classification="c",
        route=("zone", "get_status"),
        session_id=None,
    )
    assert ev.domain == "zone"


def test_table_csm_changed_domain_override() -> None:
    ev = events.TableCsmChanged(
        kind=events.TableCsmChanged.KIND,
        at=0.0,
        seq=None,
        classification="c",
        route=("system", "table_info"),
        session_id=None,
        csm_domain="area",
        old=1,
        new=2,
    )
    assert ev.domain == "area"


def test_error_classes_cover_constructors() -> None:
    err = errors.E27ProvisioningRequired()
    assert err.code is errors.E27ErrorCode.PROVISIONING_REQUIRED
    assert errors.E27ProvisioningTimeout().code is errors.E27ErrorCode.PROVISIONING_TIMEOUT
    assert errors.E27LinkInvalid().code is errors.E27ErrorCode.LINK_INVALID
    assert errors.E27AuthFailed().code is errors.E27ErrorCode.AUTH_FAILED
    assert errors.E27ProtocolError().code is errors.E27ErrorCode.PROTOCOL_ERROR
    assert errors.ProtocolError().code is errors.E27ErrorCode.PROTOCOL_ERROR
    assert errors.E27TransportError().code is errors.E27ErrorCode.TRANSPORT_ERROR
    assert errors.ConnectionLost().code is errors.E27ErrorCode.TRANSPORT_ERROR
    assert errors.E27Timeout().code is errors.E27ErrorCode.TIMEOUT
    assert errors.E27NotReady().code is errors.E27ErrorCode.NOT_READY
    assert errors.NotAuthenticatedError().code is errors.E27ErrorCode.NOT_AUTHENTICATED
    assert errors.E27MissingContext().code is errors.E27ErrorCode.MISSING_CONTEXT
    assert errors.AuthorizationRequired().code is errors.E27ErrorCode.AUTH_REQUIRED
    assert errors.PermissionDeniedError().code is errors.E27ErrorCode.PERMISSION_DENIED
    assert errors.PanelNotDisarmedError().code is errors.E27ErrorCode.PANEL_NOT_DISARMED
    assert errors.InvalidCredentials().code is errors.E27ErrorCode.INVALID_CREDENTIALS
    assert errors.InvalidLinkKeys().code is errors.E27ErrorCode.LINK_INVALID
    assert errors.InvalidPin().code is errors.E27ErrorCode.INVALID_PIN
    assert errors.MissingPinError().code is errors.E27ErrorCode.INVALID_PIN
    assert errors.InvalidPinError().code is errors.E27ErrorCode.INVALID_PIN
    assert errors.CryptoError().code is errors.E27ErrorCode.PROTOCOL_ERROR
    assert isinstance(errors.Elke27Error("x", code="c", is_transient=False), Exception)
    assert isinstance(errors.Elke27TransientError("x"), Exception)
    assert isinstance(errors.Elke27ConnectionError("x"), Exception)
    assert isinstance(errors.Elke27TimeoutError("x"), Exception)
    assert isinstance(errors.Elke27DisconnectedError("x"), Exception)
    assert isinstance(errors.Elke27AuthError("x"), Exception)
    assert isinstance(errors.Elke27LinkRequiredError("x"), Exception)
    assert isinstance(errors.Elke27PermissionError("x"), Exception)
    assert isinstance(errors.Elke27PinRequiredError("x"), Exception)
    assert isinstance(errors.Elke27ProtocolError("x"), Exception)
    assert isinstance(errors.Elke27CryptoError("x"), Exception)
    assert isinstance(errors.Elke27InvalidArgument("x"), Exception)
    assert errors._scrub_text("") == ""
    assert "pin=***" in errors._scrub_text("pin=1234")
    err2 = errors.Elke27Error("pin=1234", code="c", is_transient=True)
    assert str(err2) == "pin=***"
    assert "code='c'" in repr(err2)
    invalid = errors.Elke27InvalidArgument("pin=1234")
    assert str(invalid) == "pin=***"
    assert "Elke27InvalidArgument" in repr(invalid)


def test_frame_build_protocol_byte_validation() -> None:
    with pytest.raises(ValueError):
        framing.frame_build(protocol_byte=256, data_frame=b"")


def test_deframe_invalid_state_and_pending_debug(caplog: pytest.LogCaptureFixture) -> None:
    state = framing.DeframeState()
    state.rcv_state = "BAD"  # type: ignore[assignment]
    results = framing.deframe_feed(state, b"\x00")
    assert results
    assert results[0].ok is False

    state = framing.DeframeState()
    state.rcv_state = framing.FrameStates.WAIT_DATA
    state.msglength = 100
    state.input_buffer.extend(b"\x01")
    caplog.set_level(logging.DEBUG, logger=framing.LOG.name)
    results = framing.deframe_feed(state, b"\x02")
    assert results == []
