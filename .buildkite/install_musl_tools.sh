#!/usr/bin/env bash
set -euo pipefail

if command -v musl-gcc >/dev/null 2>&1; then
  exit 0
fi
if [[ $(id -u) != 0 ]] || ! command -v apt-get >/dev/null 2>&1; then
  echo "musl-gcc is required to build static Data Plane binaries" >&2
  exit 1
fi

apt_options=(-o Acquire::Retries=5)
# musl-tools and file come from Debian main. Use a dedicated source list for
# these build dependencies so an expired, unrelated security suite does not
# prevent installation on older builders. APT signature and expiry checks
# remain enabled, and the builder's system source configuration is unchanged.
. /etc/os-release
if [[ ${ID:-} == debian && -n ${VERSION_CODENAME:-} ]]; then
  source_dir=$(mktemp -d)
  trap 'rm -rf "$source_dir"' EXIT
  printf 'deb https://mirrors.huaweicloud.com/debian %s main\n' "$VERSION_CODENAME" > "$source_dir/sources.list"
  apt_options+=(-o "Dir::Etc::sourcelist=$source_dir/sources.list" -o Dir::Etc::sourceparts=-)
fi

apt-get "${apt_options[@]}" update
apt-get "${apt_options[@]}" install -y --no-install-recommends musl-tools file
