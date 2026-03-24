import argparse
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlretrieve


DEFAULT_BUCKET = "openyuanrong"
DEFAULT_SERVER = "obs.cn-southwest-2.myhuaweicloud.com"


def current_timestamp():
    return datetime.now().strftime("%Y%m%d%H%M%S")


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
    if (
        parsed.scheme in ("http", "https")
        and parsed.netloc == "github.com"
        and len(segments) >= 6
        and segments[2] == "archive"
        and segments[3] == "refs"
    ):
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


def validate_args(kind, channel, version, target, file_path=None, source_url=None):
    if kind == "build":
        if not file_path:
            raise ValueError("--file is required when --kind build is used")
        if channel == "release" and not version:
            raise ValueError("--version is required when --channel release is used")
        return
    if target is None and source_url is None:
        raise ValueError("--target or --source-url is required when --kind thirdparty is used")
    if file_path is None and source_url is None:
        raise ValueError("--file or --source-url is required when --kind thirdparty is used")
    if channel not in (None, ""):
        raise ValueError("--kind thirdparty does not support --channel")
    if version:
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
        validate_args(
            kind=kind,
            channel=None,
            version=version,
            target=normalized_target,
            file_path=file_path,
            source_url=source_url,
        )
        return f"thirdparty/{normalized_target}/{filename}"

    validate_args(
        kind=kind,
        channel=channel,
        version=version,
        target=target,
        file_path=file_path,
        source_url=source_url,
    )
    if channel == "release":
        return f"release/{version}/{platform}/{arch}/{filename}"
    resolved_timestamp = timestamp or current_timestamp()
    return f"daily/{resolved_timestamp}/{platform}/{arch}/{filename}"


def build_public_url(server, bucket, object_path):
    return f"https://{bucket}.{server}/{object_path}"


def create_obs_client(access_key_id, secret_access_key, server):
    try:
        from obs import ObsClient
    except ModuleNotFoundError:
        print("please install obs client: pip install esdk-obs-python", file=sys.stderr)
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
    print(f"\r {percent:.0f}% {speed:.2f} MB/S", end="")


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
    print(f"Downloading {download_url} to {temp_file.name}")
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
    print(
        f"Uploading file {upload_file_path} to bucket {args.bucket} as object {object_path}"
    )
    try:
        response = client.putFile(
            args.bucket,
            object_path,
            upload_file_path,
            progressCallback=upload_progress,
        )
        print()
        if response.status < 300:
            print("Put File Succeeded")
            print("requestId:", response.requestId)
            print("etag:", response.body.etag)
            print("versionId:", response.body.versionId)
            print("storageClass:", response.body.storageClass)
            print("url:", build_public_url(args.server, args.bucket, object_path))
            return 0
        print("Put File Failed")
        print("requestId:", response.requestId)
        print("errorCode:", response.errorCode)
        print("errorMessage:", response.errorMessage)
        return 1
    except Exception:
        print("Put File Failed")
        print(traceback.format_exc())
        return 1
    finally:
        client.close()
        if cleanup_file and os.path.exists(cleanup_file):
            os.unlink(cleanup_file)


def main(argv=None):
    args = parse_args(argv)
    args.target = normalize_target(args.target)
    validate_args(
        kind=args.kind,
        channel=args.channel if args.kind == "build" else None,
        version=args.version,
        target=args.target,
        file_path=args.file,
        source_url=args.source_url,
    )
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
        print(object_path)
        print(build_public_url(args.server, args.bucket, object_path))
        return 0
    if not args.ak or not args.sk:
        raise ValueError("OBS credentials are required: set --ak/--sk or env vars")
    return upload_file(args)


if __name__ == "__main__":
    sys.exit(main())
