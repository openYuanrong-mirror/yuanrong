# shellcheck shell=sh
# Provision sccache as a content-addressed rustc cache on the persistent
# hostPath volume ($CACHE_BASE/sccache).
#
# Why: bazel runs the //api/rust cargo genrule from a fresh exec-root path every
# build, which busts cargo's own target-dir fingerprints (path/mtime sensitive)
# -> full ~48min recompile each time even on the same node. sccache keys on the
# preprocessed compiler input + flags (NOT source paths or mtimes), so compiled
# crates are reused across builds regardless of where bazel checked them out.
#
# Meant to be SOURCED (`. .buildkite/setup_sccache.sh`) AFTER CACHE_BASE is set,
# so the exported env reaches build.sh / bazel. POSIX sh (build runs under dash).
# Optional: if sccache cannot be provisioned, the build proceeds WITHOUT a rustc
# wrapper (only slower) — it must never break the build.
#
# Exports: SCCACHE_DIR, SCCACHE_CACHE_SIZE, SCCACHE_IDLE_TIMEOUT, CARGO_INCREMENTAL,
# and RUSTC_WRAPPER (only when a working sccache binary is found).

: "${CACHE_BASE:?setup_sccache.sh: CACHE_BASE must be set}"

export SCCACHE_DIR="${SCCACHE_DIR:-$CACHE_BASE/sccache}"
export SCCACHE_CACHE_SIZE="${SCCACHE_CACHE_SIZE:-20G}"
export SCCACHE_IDLE_TIMEOUT=0
# sccache is incompatible with cargo incremental compilation (release defaults to
# off, but pin it so a stray CARGO_INCREMENTAL=1 can't silently disable caching).
export CARGO_INCREMENTAL=0
mkdir -p "$SCCACHE_DIR" "$CACHE_BASE/bin"

_sccache_bin="$(command -v sccache 2>/dev/null || true)"
if [ -z "$_sccache_bin" ] && [ -x "$CACHE_BASE/bin/sccache" ]; then
	_sccache_bin="$CACHE_BASE/bin/sccache"
fi

if [ -z "$_sccache_bin" ]; then
	_ver="0.8.2"
	_pkg="sccache-v${_ver}-x86_64-unknown-linux-musl"
	echo "sccache: not present; fetching prebuilt v${_ver} -> $CACHE_BASE/bin" >&2
	if curl -fsSL --connect-timeout 10 --max-time 180 \
		"https://github.com/mozilla/sccache/releases/download/v${_ver}/${_pkg}.tar.gz" \
		-o /tmp/sccache.tgz &&
		tar -xzf /tmp/sccache.tgz -C /tmp &&
		install -m 0755 "/tmp/${_pkg}/sccache" "$CACHE_BASE/bin/sccache"; then
		_sccache_bin="$CACHE_BASE/bin/sccache"
	elif command -v cargo >/dev/null 2>&1 &&
		cargo install sccache --version "^0.8" --root "$CACHE_BASE/sccache-cargo" --locked >&2 2>&1; then
		_sccache_bin="$CACHE_BASE/sccache-cargo/bin/sccache"
	fi
fi

if [ -n "$_sccache_bin" ] && "$_sccache_bin" --version >/dev/null 2>&1; then
	export RUSTC_WRAPPER="$_sccache_bin"
	echo "sccache enabled: $_sccache_bin (SCCACHE_DIR=$SCCACHE_DIR, max=$SCCACHE_CACHE_SIZE)" >&2
else
	echo "WARNING: sccache unavailable; building without rustc cache (slower, not fatal)" >&2
	unset RUSTC_WRAPPER 2>/dev/null || true
fi
