#!/usr/bin/env python3

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class KeepAliveHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bind")
    parser.add_argument("port", type=int)
    parser.add_argument("directory")
    args = parser.parse_args()
    handler = partial(KeepAliveHandler, directory=args.directory)
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
