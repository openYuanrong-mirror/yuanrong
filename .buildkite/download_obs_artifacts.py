#!/usr/bin/env python3
import argparse
import fnmatch
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
    parser.add_argument("--all", action="store_true", help="download all matches instead of the newest match per pattern")
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
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = read_entries(args.urls_root)
    selected = []
    for pattern in args.pattern:
        matches = [(name, url) for name, url in entries if fnmatch.fnmatch(name, pattern)]
        if not matches:
            print(f"No OBS URL matched pattern: {pattern}", file=sys.stderr)
            return 1
        selected.extend(matches if args.all else [sorted(matches)[-1]])

    seen = set()
    for name, url in selected:
        if (name, url) in seen:
            continue
        seen.add((name, url))
        output = output_dir / name
        print(f"Downloading {url} -> {output}", file=sys.stderr)
        download(url, output)
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
