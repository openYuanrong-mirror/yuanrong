#!/usr/bin/env bash
set -euo pipefail

python_bin="${1:?python interpreter required}"
wheel="${2:?wheel path required}"
version="$(${python_bin} -c 'import platform; print(platform.python_version())')"
[ "${version}" = "3.14.6" ] || { echo "Expected Python 3.14.6, got ${version}" >&2; exit 1; }
case "$(basename "${wheel}")" in
*-cp314-cp314-*.whl) ;;
*) echo "Expected a cp314 wheel, got ${wheel}" >&2; exit 1 ;;
esac
wheel_listing="$(unzip -l "${wheel}")"
if grep -Eq 'fnruntime.*(cp313|cpython-313)' <<<"${wheel_listing}"; then
    echo "Found cp313 fnruntime residue in ${wheel}" >&2
    exit 1
fi
venv="$(mktemp -d)"
trap 'rm -rf "${venv}"' EXIT
"${python_bin}" -m venv "${venv}"
"${venv}/bin/python" -m pip install --index-url \
    "${PIP_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple}" "${wheel}"
"${venv}/bin/python" -c 'import yr; from yr.cli import scripts; assert callable(scripts.main)'
"${venv}/bin/yrcli" --help >/dev/null
