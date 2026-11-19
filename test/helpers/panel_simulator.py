"""Loopback E27 panel simulator for keepalive tests (#149).

Speaks the real wire protocol to ``Session``: cleartext HELLO with link-key
encrypted session keys, then framed, schema-0 encrypted JSON. It answers
``system.r_u_alive`` probes and can drop or delay those replies, call a hook when
a probe or another request arrives, push unsolicited ``seq=0`` traffic, refuse
HELLO with an error code, and optionally acknowledge other requests with an
empty success body. Dummy keys only.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from elke27_lib.framing_loop import DeframeState, deframe_feed, frame_build
from elke27_lib.linking_thread import E27Identity, E27LinkKeys
from elke27_lib.presentation_loop import (
    API_LINK_IV,
    decrypt_schema0_envelope,
    encrypt_schema0_envelope,
)
from elke27_lib.session_thread import SessionConfig
from elke27_lib.util import swap_endianness

LINK_KEY_HEX = "00112233445566778899aabbccddeeff"
LINK_KEYS = E27LinkKeys(
    tempkey_hex="ffeeddccbbaa99887766554433221100",
    linkkey_hex=LINK_KEY_HEX,
    linkhmac_hex="0011223344556677889900112233445566778899",
)
IDENTITY = E27Identity(mn="0222", sn="001122334455", fwver="1.0", hwver="1.0", osver="1.0")
SESSION_ID = 4242


def _encrypt_with_link_key(plaintext: bytes) -> str:
    key = swap_endianness(bytes.fromhex(LINK_KEY_HEX))
    encryptor = Cipher(algorithms.AES(key), modes.CBC(API_LINK_IV)).encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return swap_endianness(ciphertext).hex()


class PanelSimulator:
    """One-connection loopback panel. Use as a context manager."""

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.drop_probe_replies = 0
        self.probe_reply_delay_s = 0.0
        self.unsolicited_after_probe_s: float | None = None
        self.answer_commands_after_s: float | None = None
        self.on_probe: Callable[[], None] | None = None
        self.on_command: Callable[[], None] | None = None
        self.hello_error_code: int | None = None
        self.probe_times: list[float] = []
        self.probe_seqs: list[int | None] = []
        self._session_key = os.urandom(16)
        self._hmac_key = os.urandom(32)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind((self.host, 0))
        self._listener.listen(1)
        self._listener.settimeout(0.2)
        self.port: int = self._listener.getsockname()[1]
        self._conn: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._envelope_seq = 1
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="panel-sim", daemon=True)

    def __enter__(self) -> PanelSimulator:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._conn is not None:
            self._conn.close()
        self._listener.close()

    def session_config(self, *, interval_s: float, timeout_s: float) -> SessionConfig:
        """Production defaults except the address and the keepalive timing."""
        return SessionConfig(
            host=self.host,
            port=self.port,
            keepalive_interval_s=interval_s,
            keepalive_timeout_s=timeout_s,
        )

    @property
    def probes(self) -> int:
        return len(self.probe_times)

    def send_unsolicited(self) -> None:
        """Push one unsolicited (``seq=0``) system message, as the panel does."""
        self._send({"seq": 0, "session_id": SESSION_ID, "system": {"r_u_alive": {}}})

    def drop_connection(self) -> None:
        """Hang up on the client, as a panel reboot or network drop would."""
        conn = self._conn
        if conn is None:
            return
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_RDWR)

    def _send(self, obj: dict[str, Any]) -> None:
        conn = self._conn
        if conn is None:
            return
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        with self._send_lock:
            protocol, ciphertext = encrypt_schema0_envelope(
                payload=payload,
                session_key=self._session_key,
                src=0,
                dest=1,
                envelope_seq=self._envelope_seq,
            )
            self._envelope_seq += 1
            try:
                conn.sendall(frame_build(protocol_byte=protocol, data_frame=ciphertext))
            except OSError:
                return

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(0.1)
            self._conn = conn
            if self._hello(conn):
                self._pump(conn)
            self._conn = None
            conn.close()

    def _hello(self, conn: socket.socket) -> bool:
        buf = b""
        decoder = json.JSONDecoder()
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                return False
            buf += chunk
            try:
                decoder.raw_decode(buf.decode("utf-8"))
            except ValueError:
                continue
            refusal = self.hello_error_code
            if refusal is not None:
                conn.sendall(json.dumps({"hello": {"error_code": refusal}}).encode("utf-8"))
                return False
            reply = {
                "hello": {
                    "session_id": SESSION_ID,
                    "sk": _encrypt_with_link_key(self._session_key),
                    "shm": _encrypt_with_link_key(self._hmac_key),
                    "error_code": 0,
                }
            }
            conn.sendall(json.dumps(reply, separators=(",", ":")).encode("utf-8"))
            return True
        return False

    def _pump(self, conn: socket.socket) -> None:
        state = DeframeState()
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            for result in deframe_feed(state, chunk):
                frame = result.frame_no_crc
                if not result.ok or frame is None:
                    continue
                envelope = decrypt_schema0_envelope(
                    protocol_byte=frame[0],
                    ciphertext=frame[3:],
                    session_key=self._session_key,
                )
                self._handle(json.loads(envelope.payload.decode("utf-8")))

    def _handle(self, msg: dict[str, Any]) -> None:
        system = msg.get("system")
        if not isinstance(system, dict) or "r_u_alive" not in system:
            command_hook = self.on_command
            if command_hook is not None:
                command_hook()
            self._maybe_answer_command(msg)
            return
        self.probe_times.append(time.monotonic())
        self.probe_seqs.append(msg.get("seq"))
        hook = self.on_probe
        if hook is not None:
            hook()
        threading.Thread(
            target=self._answer_probe, args=(msg.get("seq"),), name="panel-sim-reply", daemon=True
        ).start()

    def _maybe_answer_command(self, msg: dict[str, Any]) -> None:
        delay = self.answer_commands_after_s
        if delay is None:
            return
        routes = [(key, value) for key, value in msg.items() if isinstance(value, dict)]
        if len(routes) != 1:
            return
        domain, body = routes[0]
        names = list(body)
        if len(names) != 1:
            return
        reply = {
            "seq": msg.get("seq"),
            "session_id": SESSION_ID,
            domain: {names[0]: {"error_code": 0}},
        }
        timer = threading.Timer(delay, self._send, args=(reply,))
        timer.daemon = True
        timer.start()

    def _answer_probe(self, seq: object) -> None:
        unsolicited_after = self.unsolicited_after_probe_s
        if unsolicited_after is not None:
            time.sleep(unsolicited_after)
            self.send_unsolicited()
        if self.drop_probe_replies > 0:
            self.drop_probe_replies -= 1
            return
        if self.probe_reply_delay_s:
            time.sleep(self.probe_reply_delay_s)
        self._send(
            {
                "seq": seq,
                "session_id": SESSION_ID,
                "system": {"r_u_alive": {"error_code": 0}},
            }
        )
