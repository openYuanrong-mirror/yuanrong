#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import fnmatch
import logging
import pathlib
import sys
import time
import urllib.parse
import urllib.request


def parse_args():
    parser = argparse.ArgumentParser(description="Download artifacts from OBS URL manifests")
    parser.add_argument("--urls-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pattern", action="append", required=True)
    parser.add_argument(
        "--all",
        action="store_true",
        help="download all matches instead of the newest match per pattern",
    )
    return parser.parse_args()


def read_entries(urls_root):
    root = pathlib.Path(urls_root)
    entries = []
    for path in sorted(root.rglob("obs-urls.txt")):
        for line in path.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            entries.append((parts[0], parts[1]))
    return entries


def normalize_url(url):
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def download(url, output):
    url = normalize_url(url)
    last_error = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(url, timeout=300) as response, output.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return
        except Exception as exc:
            last_error = exc
            output.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = read_entries(args.urls_root)
    selected = []
    for pattern in args.pattern:
        matches = [(name, url) for name, url in entries if fnmatch.fnmatch(name, pattern)]
        if not matches:
            logging.error("No OBS URL matched pattern: %s", pattern)
            return 1
        selected.extend(matches if args.all else [sorted(matches)[-1]])

    seen = set()
    for name, url in selected:
        if (name, url) in seen:
            continue
        seen.add((name, url))
        output = output_dir / name
        logging.info("Downloading %s -> %s", url, output)
        download(url, output)
        logging.info("%s", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
