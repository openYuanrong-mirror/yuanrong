#!/bin/bash
# 手动触发 Buildkite 构建并可选轮询结果
set -euo pipefail

TOKEN="${BUILDKITE_API_TOKEN:-}"
ORG="${BUILDKITE_ORG:-yuchao-wang}"
PIPELINE="${BUILDKITE_PIPELINE:-yuanrong}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT="$(git rev-parse HEAD)"
WATCH_MODE=false
REPOSITORY_OVERRIDE=""
MESSAGE=""
declare -a EXTRA_ENVS=()

usage() {
    cat <<'EOF'
Usage: bash tools/trigger_build.sh [options] [branch]

Options:
  --watch                Poll build status until it finishes
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
  bash tools/trigger_build.sh \
    --repo https://gitcode.com/yuchaow/yuanrong.git \
    --branch feature/sandbox-macos-sync \
    --env ENABLE_MACOS_SDK=false
EOF
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
        --repo)
            REPOSITORY_OVERRIDE="$2"
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift
            ;;
        --commit)
            COMMIT="$2"
            shift
            ;;
        --message)
            MESSAGE="$2"
            shift
            ;;
        --env)
            EXTRA_ENVS+=("$2")
            shift
            ;;
        --org)
            ORG="$2"
            shift
            ;;
        --pipeline)
            PIPELINE="$2"
            shift
            ;;
        -h|--help)
            usage
            exit 0
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

if [[ "$WATCH_MODE" == true ]]; then
    echo "👀 Watching build #$BUILD_NO (polling every 60s)..."
    while true; do
        sleep 60
        INFO=$(curl -sS -H "Authorization: Bearer $TOKEN" \
          "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO")

        STATE=$(echo "$INFO" | jq -r '.state')
        TIMESTAMP=$(date '+%H:%M:%S')
        echo "[$TIMESTAMP] Current State: $STATE"

        if [[ "$STATE" != "running" && "$STATE" != "scheduled" ]]; then
            echo "🏁 Build #$BUILD_NO finished with state: $STATE"

            if [[ "$STATE" == "failed" ]]; then
                echo "❌ Fetching failure details..."
                JOB_ID=$(echo "$INFO" | jq -r '.jobs[] | select(.state=="failed") | .id' | head -n 1)
                if [[ -n "$JOB_ID" ]]; then
                    curl -sS -H "Authorization: Bearer $TOKEN" \
                      "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO/jobs/$JOB_ID/log.txt" | tail -n 50
                fi
            fi
            break
        fi
    done
fi
