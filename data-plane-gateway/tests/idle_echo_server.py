#!/usr/bin/env python3
"""Small TCP echo service used by the local three-VM idle-stream probe."""

import socket
import sys
import threading


def serve(connection: socket.socket) -> None:
    with connection:
        while True:
            data = connection.recv(65536)
            if not data:
                return
            connection.sendall(data)


def main() -> None:
    host = sys.argv[1]
    port = int(sys.argv[2])
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen()
        while True:
            connection, _ = listener.accept()
            threading.Thread(target=serve, args=(connection,), daemon=True).start()


if __name__ == "__main__":
    main()
