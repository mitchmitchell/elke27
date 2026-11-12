"""Blocking socket helpers for discovery (worker thread only).

Exports ``UDP_IPV4_FAMILY`` and ``UDP_DGRAM`` so loop modules can pass
``getaddrinfo`` family/type without importing ``socket``.
"""

from __future__ import annotations

import ctypes
import socket
import sys

UDP_IPV4_FAMILY: int = socket.AF_INET
UDP_DGRAM: int = socket.SOCK_DGRAM


def create_udp_socket() -> socket.socket:
    sock = socket.socket(UDP_IPV4_FAMILY, UDP_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.setblocking(False)
    return sock


def _ipv4_broadcast_addresses() -> list[str]:  # pragma: no cover
    if sys.platform == "win32":
        return []

    if sys.platform.startswith(("darwin", "freebsd")):

        class _SockaddrBsd(ctypes.Structure):
            _fields_ = [
                ("sa_len", ctypes.c_uint8),
                ("sa_family", ctypes.c_uint8),
                ("sa_data", ctypes.c_char * 14),
            ]

        class _InAddrBsd(ctypes.Structure):
            _fields_ = [("s_addr", ctypes.c_uint32)]

        class _SockaddrInBsd(ctypes.Structure):
            _fields_ = [
                ("sin_len", ctypes.c_uint8),
                ("sin_family", ctypes.c_uint8),
                ("sin_port", ctypes.c_uint16),
                ("sin_addr", _InAddrBsd),
                ("sin_zero", ctypes.c_char * 8),
            ]

        sockaddr_type = _SockaddrBsd
        sockaddr_in_type = _SockaddrInBsd

    else:

        class _SockaddrPosix(ctypes.Structure):
            _fields_ = [
                ("sa_family", ctypes.c_ushort),
                ("sa_data", ctypes.c_char * 14),
            ]

        class _InAddrPosix(ctypes.Structure):
            _fields_ = [("s_addr", ctypes.c_uint32)]

        class _SockaddrInPosix(ctypes.Structure):
            _fields_ = [
                ("sin_family", ctypes.c_ushort),
                ("sin_port", ctypes.c_uint16),
                ("sin_addr", _InAddrPosix),
                ("sin_zero", ctypes.c_char * 8),
            ]

        sockaddr_type = _SockaddrPosix
        sockaddr_in_type = _SockaddrInPosix

    class _IfAddrs(ctypes.Structure):
        pass

    _IfAddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(_IfAddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.POINTER(sockaddr_type)),
        ("ifa_netmask", ctypes.POINTER(sockaddr_type)),
        ("ifa_dstaddr", ctypes.POINTER(sockaddr_type)),
        ("ifa_data", ctypes.c_void_p),
    ]

    libc = ctypes.CDLL(None)
    getifaddrs = libc.getifaddrs
    freeifaddrs = libc.freeifaddrs
    getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(_IfAddrs))]
    getifaddrs.restype = ctypes.c_int
    freeifaddrs.argtypes = [ctypes.POINTER(_IfAddrs)]
    freeifaddrs.restype = None

    ifap = ctypes.POINTER(_IfAddrs)()
    if getifaddrs(ctypes.byref(ifap)) != 0:
        return []

    broadcasts: set[str] = set()
    IFF_UP = 0x1
    IFF_BROADCAST = 0x2
    cursor = ifap
    try:
        while cursor:
            current = cursor.contents
            if (
                not current.ifa_addr
                or not current.ifa_dstaddr
                or (current.ifa_flags & IFF_UP) == 0
                or (current.ifa_flags & IFF_BROADCAST) == 0
                or current.ifa_addr.contents.sa_family != socket.AF_INET
            ):
                cursor = current.ifa_next
                continue

            sockaddr_in = ctypes.cast(
                current.ifa_dstaddr,
                ctypes.POINTER(sockaddr_in_type),
            ).contents
            raw = ctypes.string_at(ctypes.byref(sockaddr_in.sin_addr), 4)
            broadcasts.add(socket.inet_ntoa(raw))
            cursor = current.ifa_next
    finally:
        freeifaddrs(ifap)

    return sorted(broadcasts)


def destinations_from_broadcasts(
    destination_port: int,
    address: str | None,
) -> list[tuple[str, int]]:
    if address is not None:
        return [(address, destination_port)]

    broadcast_addresses = _ipv4_broadcast_addresses()
    if not broadcast_addresses:
        return [("<broadcast>", destination_port)]
    return [(b, destination_port) for b in broadcast_addresses]
