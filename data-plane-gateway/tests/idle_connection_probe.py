#!/usr/bin/env python3
"""Prove that an open data-plane stream survives a byte-idle interval."""

import socket
import sys
import time


host = sys.argv[1]
port = int(sys.argv[2])
idle_seconds = float(sys.argv[3])

with socket.create_connection((host, port), timeout=5) as connection:
    connection.settimeout(5)
    connection.sendall(b"before-idle")
    assert connection.recv(11) == b"before-idle"
    started = time.monotonic()
    time.sleep(idle_seconds)
    connection.sendall(b"after-idle")
    assert connection.recv(10) == b"after-idle"
    elapsed = time.monotonic() - started

print(f"idle_stream_survived_seconds={elapsed:.3f}")
