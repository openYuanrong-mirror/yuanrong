#!/bin/bash
# 手动触发 Buildkite 构建并可选轮询结果
set -euo pipefail

TOKEN="${BUILDKITE_API_TOKEN:-}"
ORG="${BUILDKITE_ORG:-yuchao-wang}"
PIPELINE="${BUILDKITE_PIPELINE:-yuanrong}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT="$(git rev-parse HEAD)"
WATCH_MODE=false
POLL_INTERVAL=60
DOWNLOAD_ARTIFACTS=false
ARTIFACTS_DIR=""
ARTIFACT_PATTERN="*"
ARTIFACT_PATTERN_SET=false
RUST_FUNCTIONSYSTEM_E2E=false
FUNCTIONSYSTEM_REPO=""
FUNCTIONSYSTEM_BRANCH=""
RUST_BUILDER_IMAGE=""
REPOSITORY_OVERRIDE=""
MESSAGE=""
declare -a EXTRA_ENVS=()

usage() {
    cat <<'EOF'
Usage: bash tools/trigger_build.sh [options] [branch]

Options:
  --watch                Poll build status until it finishes
  --poll-interval <sec>  Poll interval in seconds for --watch, defaults to 60
  --download-artifacts   Download finished build artifacts after the build finishes
  --artifacts-dir <dir>  Local artifact download directory, defaults to buildkite-artifacts/build-<number>
  --artifact-pattern <glob>
                         Only download artifact paths matching this shell glob, defaults to *
  --rust-functionsystem-e2e
                         Run the Rust functionsystem black-box K8S smoke flow and download its logs
  --functionsystem-repo <url>
                         Rust functionsystem repository override for --rust-functionsystem-e2e
  --functionsystem-branch <branch>
                         Rust functionsystem branch override for --rust-functionsystem-e2e
  --rust-builder-image <image>
                         Rust-capable builder image for --rust-functionsystem-e2e
  --repo <url>           Patch the Buildkite pipeline repository before triggering
  --branch <branch>      Build branch, defaults to current branch
  --commit <sha>         Build commit, defaults to current HEAD
  --message <text>       Custom build message
  --env KEY=VALUE        Extra build env var, repeatable
  --org <slug>           Buildkite organization, defaults to yuchao-wang
  --pipeline <slug>      Buildkite pipeline, defaults to yuanrong
  -h, --help             Show this help text

Examples:
  bash tools/trigger_build.sh --watch
  bash tools/trigger_build.sh --env ENABLE_MACOS_SDK=false --watch
  bash tools/trigger_build.sh --rust-functionsystem-e2e \
    --functionsystem-branch rust-rewrite --watch
  bash tools/trigger_build.sh \
    --repo https://gitcode.com/yuchaow/yuanrong.git \
    --branch feature/sandbox-macos-sync \
    --env ENABLE_MACOS_SDK=false
EOF
}

is_safe_artifact_path() {
    local artifact_path="$1"
    case "$artifact_path" in
        ""|/*|../*|*/../*|*/..)
            return 1
            ;;
    esac
    return 0
}

require_option_value() {
    local option="$1"
    local value="${2-}"

    if [[ -z "$value" ]]; then
        echo "❌ $option requires a value" >&2
        exit 1
    fi
    printf '%s\n' "$value"
}

download_build_artifacts() {
    local build_no="$1"
    local target_dir="$2"
    local pattern="$3"
    local artifacts_url="https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$build_no/artifacts"
    local artifacts_json
    local count=0
    local skipped=0

    mkdir -p "$target_dir"
    echo "📦 Downloading finished artifacts matching '$pattern' to: $target_dir"

    artifacts_json=$(curl -sS -H "Authorization: Bearer $TOKEN" "$artifacts_url")
    while IFS= read -r artifact; do
        local state
        local artifact_path
        local download_url
        local destination

        state=$(echo "$artifact" | jq -r '.state')
        artifact_path=$(echo "$artifact" | jq -r '.path')
        download_url=$(echo "$artifact" | jq -r '.download_url')

        if [[ "$state" != "finished" ]]; then
            skipped=$((skipped + 1))
            continue
        fi
        if [[ "$artifact_path" != $pattern ]]; then
            skipped=$((skipped + 1))
            continue
        fi
        if ! is_safe_artifact_path "$artifact_path"; then
            echo "⚠️ Skipping unsafe artifact path: $artifact_path" >&2
            skipped=$((skipped + 1))
            continue
        fi

        destination="$target_dir/$artifact_path"
        mkdir -p "$(dirname "$destination")"
        echo "   ↓ $artifact_path"
        curl -fsSL -H "Authorization: Bearer $TOKEN" -o "$destination" "$download_url"
        count=$((count + 1))
    done < <(echo "$artifacts_json" | jq -c '.[]')

    echo "✅ Downloaded $count artifact(s); skipped $skipped"
}

patch_pipeline_repository() {
    local target_repo="$1"
    local pipeline_url="https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE"
    local current_repo

    current_repo=$(curl -sS -H "Authorization: Bearer $TOKEN" "$pipeline_url" | jq -r '.repository')
    if [[ "$current_repo" == "$target_repo" ]]; then
        echo "ℹ️ Pipeline repository already set to: $target_repo"
        return
    fi

    echo "🔁 Updating pipeline repository..."
    echo "   From: $current_repo"
    echo "   To:   $target_repo"

    local response
    response=$(curl -sS \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -X PATCH \
      "$pipeline_url" \
      -d "$(jq -n --arg repository "$target_repo" '{repository: $repository}')")

    local updated_repo
    updated_repo=$(echo "$response" | jq -r '.repository')
    if [[ "$updated_repo" != "$target_repo" ]]; then
        echo "❌ Failed to update pipeline repository:"
        echo "$response" | jq .
        exit 1
    fi
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --watch)
            WATCH_MODE=true
            ;;
        --poll-interval)
            POLL_INTERVAL="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --download-artifacts)
            DOWNLOAD_ARTIFACTS=true
            WATCH_MODE=true
            ;;
        --artifacts-dir)
            ARTIFACTS_DIR="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --artifact-pattern)
            ARTIFACT_PATTERN="$(require_option_value "$1" "${2-}")"
            ARTIFACT_PATTERN_SET=true
            shift
            ;;
        --rust-functionsystem-e2e)
            RUST_FUNCTIONSYSTEM_E2E=true
            WATCH_MODE=true
            DOWNLOAD_ARTIFACTS=true
            ;;
        --functionsystem-repo)
            FUNCTIONSYSTEM_REPO="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --functionsystem-branch)
            FUNCTIONSYSTEM_BRANCH="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --rust-builder-image)
            RUST_BUILDER_IMAGE="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --repo)
            REPOSITORY_OVERRIDE="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --branch)
            BRANCH="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --commit)
            COMMIT="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --message)
            MESSAGE="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --env)
            EXTRA_ENVS+=("$(require_option_value "$1" "${2-}")")
            shift
            ;;
        --org)
            ORG="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        --pipeline)
            PIPELINE="$(require_option_value "$1" "${2-}")"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            echo "❌ Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            BRANCH="$1"
            ;;
    esac
    shift
done

if [[ -z "$TOKEN" ]]; then
    echo "❌ BUILDKITE_API_TOKEN is required"
    exit 1
fi
if ! [[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]]; then
    echo "❌ --poll-interval must be a non-negative integer"
    exit 1
fi
if [[ "$RUST_FUNCTIONSYSTEM_E2E" == true ]]; then
    EXTRA_ENVS+=("ENABLE_RUST_FUNCTIONSYSTEM_ST=true")
    if [[ -n "$FUNCTIONSYSTEM_REPO" ]]; then
        EXTRA_ENVS+=("FUNCTIONSYSTEM_REPO=$FUNCTIONSYSTEM_REPO")
    fi
    if [[ -n "$FUNCTIONSYSTEM_BRANCH" ]]; then
        EXTRA_ENVS+=("FUNCTIONSYSTEM_BRANCH=$FUNCTIONSYSTEM_BRANCH")
    fi
    if [[ -n "$RUST_BUILDER_IMAGE" ]]; then
        EXTRA_ENVS+=("RUST_BUILDER_IMAGE=$RUST_BUILDER_IMAGE")
    fi
    if [[ "$ARTIFACT_PATTERN_SET" == false ]]; then
        ARTIFACT_PATTERN="artifacts/sandbox-smoke/*"
    fi
fi

if [[ -n "$REPOSITORY_OVERRIDE" ]]; then
    patch_pipeline_repository "$REPOSITORY_OVERRIDE"
fi

if [[ -z "$MESSAGE" ]]; then
    MESSAGE="Triggered via trigger_build.sh $(date '+%H:%M:%S')"
fi

ENV_JSON='{"BUILD_TARGET":"linux","BUILDKITE_AGENT_NAME":"agent-stack-k8s"}'
for entry in "${EXTRA_ENVS[@]}"; do
    if [[ "$entry" != *=* ]]; then
        echo "❌ Invalid --env value: $entry"
        echo "   Expected KEY=VALUE"
        exit 1
    fi
    key="${entry%%=*}"
    value="${entry#*=}"
    ENV_JSON=$(jq -cn --argjson env "$ENV_JSON" --arg k "$key" --arg v "$value" '$env + {($k): $v}')
done

echo "🚀 Triggering Buildkite..."
echo "   Org:    $ORG"
echo "   Pipe:   $PIPELINE"
echo "   Branch: $BRANCH"
echo "   Commit: $COMMIT"
if [[ -n "$REPOSITORY_OVERRIDE" ]]; then
    echo "   Repo:   $REPOSITORY_OVERRIDE"
fi

PAYLOAD=$(jq -n \
  --arg branch "$BRANCH" \
  --arg commit "$COMMIT" \
  --arg message "$MESSAGE" \
  --argjson env "$ENV_JSON" \
  '{
    branch: $branch,
    commit: $commit,
    message: $message,
    env: $env
  }')

RESPONSE=$(curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds" \
  -d "$PAYLOAD")

BUILD_NO=$(echo "$RESPONSE" | jq -r '.number')
URL=$(echo "$RESPONSE" | jq -r '.web_url')

if [[ "$BUILD_NO" == "null" ]]; then
    echo "❌ Failed to trigger build:"
    echo "$RESPONSE" | jq .
    exit 1
fi

echo "✅ Build #$BUILD_NO started!"
echo "🔗 View at: $URL"

BUILD_EXIT_CODE=0
if [[ "$WATCH_MODE" == true ]]; then
    echo "👀 Watching build #$BUILD_NO (polling every ${POLL_INTERVAL}s)..."
    while true; do
        sleep "$POLL_INTERVAL"
        INFO=$(curl -sS -H "Authorization: Bearer $TOKEN" \
          "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO")

        STATE=$(echo "$INFO" | jq -r '.state')
        TIMESTAMP=$(date '+%H:%M:%S')
        echo "[$TIMESTAMP] Current State: $STATE"

        if [[ "$STATE" != "running" && "$STATE" != "scheduled" ]]; then
            echo "🏁 Build #$BUILD_NO finished with state: $STATE"
            if [[ "$STATE" != "passed" ]]; then
                BUILD_EXIT_CODE=1
            fi

            if [[ "$STATE" == "failed" ]]; then
                echo "❌ Fetching failure details..."
                JOB_ID=$(echo "$INFO" | jq -r '.jobs[] | select(.state=="failed") | .id' | head -n 1)
                if [[ -n "$JOB_ID" ]]; then
                    curl -fsSL -H "Authorization: Bearer $TOKEN" \
                      "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO/jobs/$JOB_ID/log.txt" | tail -n 50 || true
                fi
            fi
            break
        fi
    done
fi

if [[ "$DOWNLOAD_ARTIFACTS" == true ]]; then
    if [[ -z "$ARTIFACTS_DIR" ]]; then
        ARTIFACTS_DIR="buildkite-artifacts/build-$BUILD_NO"
    fi
    download_build_artifacts "$BUILD_NO" "$ARTIFACTS_DIR" "$ARTIFACT_PATTERN"
fi

if [[ "$BUILD_EXIT_CODE" -ne 0 ]]; then
    exit "$BUILD_EXIT_CODE"
fi
