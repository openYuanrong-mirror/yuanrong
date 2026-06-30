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
import logging
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse
from urllib.request import urlretrieve


DEFAULT_BUCKET = "openyuanrong"
DEFAULT_SERVER = "obs.cn-southwest-2.myhuaweicloud.com"
LOGGER = logging.getLogger(__name__)


@dataclass
class UploadArgs:
    kind: str
    channel: Optional[str]
    version: Optional[str]
    target: Optional[str]
    file_path: Optional[str] = None
    source_url: Optional[str] = None


def current_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Upload build artifacts to OBS")
    parser.add_argument("--bucket", "-b", default=DEFAULT_BUCKET, help="Bucket name")
    parser.add_argument("--file", "-f", help="Local file path to upload")
    parser.add_argument(
        "--ak",
        default=os.getenv("OBS_ACCESS_KEY_ID") or os.getenv("AccessKeyID"),
        help="OBS access key ID",
    )
    parser.add_argument(
        "--sk",
        default=os.getenv("OBS_SECRET_ACCESS_KEY") or os.getenv("SecretAccessKey"),
        help="OBS secret access key",
    )
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER, help="OBS endpoint")
    parser.add_argument(
        "--kind",
        choices=("build", "thirdparty"),
        default="build",
        help="Artifact kind",
    )
    parser.add_argument(
        "--channel",
        choices=("daily", "release"),
        default="daily",
        help="Build channel, only valid for --kind build",
    )
    parser.add_argument("--arch", "-a", default="x86_64", help="Build architecture")
    parser.add_argument("--platform", "-p", default="linux", help="Build platform")
    parser.add_argument("--version", "-v", help="Release version")
    parser.add_argument(
        "--timestamp",
        help="Timestamp used for daily builds, default is current time",
    )
    parser.add_argument(
        "--target",
        help="Subpath below thirdparty/, for example boost/prebuilt/linux-x86_64",
    )
    parser.add_argument(
        "--source-url",
        help="Upstream source package URL to mirror into OBS for --kind thirdparty",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved object path without uploading",
    )
    return parser.parse_args(argv)


def normalize_target(target):
    if target is None:
        return None
    normalized = target.strip().strip("/")
    return normalized or None


def derive_filename(*, file_path=None, source_url=None):
    if file_path:
        return Path(file_path).name
    if source_url:
        parsed = urlparse(source_url)
        filename = Path(unquote(parsed.path)).name
        if filename:
            return filename
    raise ValueError("Unable to determine filename from --file or --source-url")


def normalize_source_url(source_url):
    parsed = urlparse(source_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    is_github_archive = parsed.scheme in ("http", "https") and parsed.netloc == "github.com"
    has_archive_ref = len(segments) >= 6 and segments[2] == "archive" and segments[3] == "refs"
    if is_github_archive and has_archive_ref:
        owner = segments[0]
        repo = segments[1]
        ref_kind = segments[4]
        archive_name = segments[5]
        if archive_name.endswith(".tar.gz"):
            archive_kind = "tar.gz"
            ref_name = archive_name[: -len(".tar.gz")]
        elif archive_name.endswith(".zip"):
            archive_kind = "zip"
            ref_name = archive_name[: -len(".zip")]
        else:
            return source_url
        return (
            f"https://codeload.github.com/{owner}/{repo}/"
            f"{archive_kind}/refs/{ref_kind}/{ref_name}"
        )
    return source_url


def derive_thirdparty_target(source_url):
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("--source-url must be a valid absolute URL")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) >= 2:
        return normalize_target(f"{parsed.netloc}/{segments[0]}/{segments[1]}")
    if len(segments) == 1:
        stem = Path(unquote(segments[0])).stem
        if stem:
            return normalize_target(f"{parsed.netloc}/{stem}")
    return normalize_target(parsed.netloc)


def validate_args(args: UploadArgs):
    if args.kind == "build":
        if not args.file_path:
            raise ValueError("--file is required when --kind build is used")
        if args.channel == "release" and not args.version:
            raise ValueError("--version is required when --channel release is used")
        return
    if args.target is None and args.source_url is None:
        raise ValueError("--target or --source-url is required when --kind thirdparty is used")
    if args.file_path is None and args.source_url is None:
        raise ValueError("--file or --source-url is required when --kind thirdparty is used")
    if args.channel not in (None, ""):
        raise ValueError("--kind thirdparty does not support --channel")
    if args.version:
        raise ValueError("--kind thirdparty does not support --version")


def build_object_path(
    *,
    kind,
    file_path,
    channel=None,
    platform=None,
    arch=None,
    version=None,
    timestamp=None,
    target=None,
    source_url=None,
):
    filename = derive_filename(file_path=file_path, source_url=source_url)
    if kind == "thirdparty":
        normalized_target = normalize_target(target) or derive_thirdparty_target(source_url)
        validate_args(UploadArgs(kind, None, version, normalized_target, file_path, source_url))
        return f"thirdparty/{normalized_target}/{filename}"

    validate_args(UploadArgs(kind, channel, version, target, file_path, source_url))
    if channel == "release":
        return f"release/{version}/{platform}/{arch}/{filename}"
    resolved_timestamp = timestamp or current_timestamp()
    return f"daily/{resolved_timestamp}/{platform}/{arch}/{filename}"


def build_public_url(server, bucket, object_path):
    return f"https://{bucket}.{server}/{quote(object_path, safe='/')}"


def create_obs_client(access_key_id, secret_access_key, server):
    try:
        from obs import ObsClient
    except ModuleNotFoundError:
        LOGGER.error("please install obs client: pip install esdk-obs-python")
        raise
    return ObsClient(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        server=server,
    )


def upload_progress(transferred_amount, total_amount, total_seconds):
    if total_amount <= 0 or total_seconds <= 0:
        return
    speed = transferred_amount / total_seconds / 1024 / 1024
    percent = transferred_amount * 100.0 / total_amount
    LOGGER.info("%s%% %.2f MB/S", f"{percent:.0f}", speed)


def resolve_upload_source(args):
    if args.file:
        return args.file, None
    if not args.source_url:
        raise ValueError("No upload source resolved")
    filename = derive_filename(source_url=args.source_url)
    suffix = "".join(Path(filename).suffixes)
    temp_file = tempfile.NamedTemporaryFile(
        prefix="thirdparty-mirror-",
        suffix=suffix,
        delete=False,
    )
    temp_file.close()
    download_url = normalize_source_url(args.source_url)
    LOGGER.info("Downloading %s to %s", download_url, temp_file.name)
    urlretrieve(download_url, temp_file.name)
    return temp_file.name, temp_file.name


def upload_file(args):
    upload_file_path, cleanup_file = resolve_upload_source(args)
    client = create_obs_client(args.ak, args.sk, args.server)
    object_file_path = upload_file_path
    if args.kind == "thirdparty" and args.source_url:
        object_file_path = None
    object_path = build_object_path(
        kind=args.kind,
        channel=args.channel if args.kind == "build" else None,
        file_path=object_file_path,
        platform=args.platform,
        arch=args.arch,
        version=args.version,
        timestamp=args.timestamp,
        target=normalize_target(args.target),
        source_url=args.source_url,
    )
    LOGGER.info("Uploading file %s to bucket %s as object %s", upload_file_path, args.bucket, object_path)
    try:
        response = client.putFile(
            args.bucket,
            object_path,
            upload_file_path,
            progressCallback=upload_progress,
        )
        if response.status < 300:
            LOGGER.info("Put File Succeeded")
            LOGGER.info("requestId: %s", response.requestId)
            LOGGER.info("etag: %s", response.body.etag)
            LOGGER.info("versionId: %s", response.body.versionId)
            LOGGER.info("storageClass: %s", response.body.storageClass)
            LOGGER.info("url: %s", build_public_url(args.server, args.bucket, object_path))
            return 0
        LOGGER.error("Put File Failed")
        LOGGER.error("requestId: %s", response.requestId)
        LOGGER.error("errorCode: %s", response.errorCode)
        LOGGER.error("errorMessage: %s", response.errorMessage)
        return 1
    except Exception:
        LOGGER.error("Put File Failed")
        LOGGER.error("%s", traceback.format_exc())
        return 1
    finally:
        client.close()
        if cleanup_file and os.path.exists(cleanup_file):
            os.unlink(cleanup_file)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    args.target = normalize_target(args.target)
    validate_args(UploadArgs(
        args.kind,
        args.channel if args.kind == "build" else None,
        args.version,
        args.target,
        args.file,
        args.source_url,
    ))
    if args.file and not os.path.isfile(args.file):
        raise ValueError(f"--file does not exist: {args.file}")
    object_path = build_object_path(
        kind=args.kind,
        channel=args.channel if args.kind == "build" else None,
        file_path=args.file,
        platform=args.platform,
        arch=args.arch,
        version=args.version,
        timestamp=args.timestamp,
        target=args.target,
        source_url=args.source_url,
    )
    if args.dry_run:
        LOGGER.info("%s", object_path)
        LOGGER.info("%s", build_public_url(args.server, args.bucket, object_path))
        return 0
    if not args.ak or not args.sk:
        raise ValueError("OBS credentials are required: set --ak/--sk or env vars")
    return upload_file(args)


if __name__ == "__main__":
    sys.exit(main())
