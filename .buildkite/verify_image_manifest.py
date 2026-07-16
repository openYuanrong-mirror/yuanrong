#!/usr/bin/env python3
"""Validate immutable image digests and registry manifest platforms."""

import argparse
import json
import pathlib
import re
import sys


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ARCH_ALIASES = {"x86_64": "amd64", "aarch64": "arm64"}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read manifest JSON {path}: {exc}")


def normalize_platform(platform: dict) -> str:
    os_name = platform.get("os", "")
    architecture = ARCH_ALIASES.get(platform.get("architecture", ""), platform.get("architecture", ""))
    if not os_name or not architecture:
        fail(f"incomplete platform descriptor: {platform!r}")
    return f"{os_name}/{architecture}"


def validate_digest(digest: str, description: str) -> str:
    if not DIGEST_RE.fullmatch(digest or ""):
        fail(f"{description} has no immutable sha256 digest: {digest!r}")
    return digest


def append_evidence(path: pathlib.Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\t".join(fields) + "\n")


def validate_source(args: argparse.Namespace) -> None:
    data = load_json(args.input)
    descriptor = data.get("Descriptor") if isinstance(data, dict) else None
    if not isinstance(descriptor, dict):
        descriptor = data if isinstance(data, dict) and "digest" in data and "platform" in data else None
    if not isinstance(descriptor, dict):
        fail("source inspection does not contain one image Descriptor")
    digest = validate_digest(descriptor.get("digest", ""), args.image)
    actual_platform = normalize_platform(descriptor.get("platform", {}))
    if actual_platform != args.expected_platform:
        fail(f"{args.image} is {actual_platform}, expected {args.expected_platform}; refusing annotation")
    append_evidence(args.evidence, ["source", args.image, digest, actual_platform])
    print(digest)


def validate_final(args: argparse.Namespace) -> None:
    data = load_json(args.input)
    manifests = data.get("manifests") if isinstance(data, dict) else None
    if not isinstance(manifests, list):
        fail("final inspection does not contain a manifests list")
    actual_platforms = []
    source_digests = []
    for descriptor in manifests:
        if not isinstance(descriptor, dict):
            fail(f"invalid final descriptor: {descriptor!r}")
        actual_platforms.append(normalize_platform(descriptor.get("platform", {})))
        source_digests.append(validate_digest(descriptor.get("digest", ""), args.image))
    expected_platforms = args.expected_platform
    if len(actual_platforms) != len(expected_platforms) or set(actual_platforms) != set(expected_platforms):
        fail(f"{args.image} platforms are {actual_platforms}, expected exactly {expected_platforms}")
    if len(set(actual_platforms)) != len(actual_platforms):
        fail(f"{args.image} contains duplicate platforms: {actual_platforms}")
    final_digest = validate_digest(args.digest, args.image)
    platforms = ",".join(expected_platforms)
    append_evidence(
        args.evidence,
        ["final", args.image, final_digest, platforms, ",".join(source_digests)],
    )
    print(final_digest)


def extract_push_digest(args: argparse.Namespace) -> None:
    text = args.input.read_text(encoding="utf-8", errors="replace")
    digests = re.findall(r"sha256:[0-9a-f]{64}", text)
    if not digests:
        fail(f"manifest push output {args.input} did not contain an immutable digest")
    print(digests[-1])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    source = subparsers.add_parser("source")
    source.add_argument("--input", required=True, type=pathlib.Path)
    source.add_argument("--image", required=True)
    source.add_argument("--expected-platform", required=True)
    source.add_argument("--evidence", required=True, type=pathlib.Path)
    source.set_defaults(func=validate_source)
    final = subparsers.add_parser("final")
    final.add_argument("--input", required=True, type=pathlib.Path)
    final.add_argument("--image", required=True)
    final.add_argument("--digest", required=True)
    final.add_argument("--expected-platform", required=True, action="append")
    final.add_argument("--evidence", required=True, type=pathlib.Path)
    final.set_defaults(func=validate_final)
    push = subparsers.add_parser("push-digest")
    push.add_argument("--input", required=True, type=pathlib.Path)
    push.set_defaults(func=extract_push_digest)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        print(f"manifest validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
