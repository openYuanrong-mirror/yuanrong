#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
build_script="$repo_root/build.sh"

default_value=$(sed -n 's/^ENABLE_GLOO="\([^"]*\)"/\1/p' "$build_script" | head -n 1)
if [[ "$default_value" != "false" ]]; then
    echo "expected ENABLE_GLOO to default to false, got: ${default_value:-missing}" >&2
    exit 1
fi

grep -F -- '-G enable gloo collective operations (default: disabled)' "$build_script" >/dev/null

if ! awk '
    /^[[:space:]]*G\)/ { in_gloo_option = 1; next }
    in_gloo_option && /ENABLE_GLOO="true"/ { found = 1; exit }
    in_gloo_option && /^[[:space:]]*;;/ { exit }
    END { exit(found ? 0 : 1) }
' "$build_script"; then
    echo "expected -G to enable Gloo explicitly" >&2
    exit 1
fi
