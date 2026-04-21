#!/bin/bash
# 手动触发 Buildkite 构建并可选轮询结果
set -e

TOKEN="${BUILDKITE_API_TOKEN:?BUILDKITE_API_TOKEN is required}"
ORG="yuchao-wang"
PIPELINE="yuanrong"
BRANCH="feature/ci-buildkite-k8s"
WATCH_MODE=false

# 参数解析
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --watch) WATCH_MODE=true ;;
        *) BRANCH="$1" ;;
    esac
    shift
done

# 获取 Commit SHA
COMMIT=$(git rev-parse "HEAD")

echo "🚀 Triggering Buildkite..."
echo "   Branch: $BRANCH"
echo "   Commit: $COMMIT"

PAYLOAD=$(jq -n \
  --arg branch "$BRANCH" \
  --arg commit "$COMMIT" \
  --arg message "Triggered via trigger_build.sh $(date '+%H:%M:%S')" \
  '{
    branch: $branch,
    commit: $commit,
    message: $message,
    env: { BUILD_TARGET: "linux" }
  }')

RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds" \
  -d "$PAYLOAD")

BUILD_NO=$(echo "$RESPONSE" | jq -r '.number')
URL=$(echo "$RESPONSE" | jq -r '.web_url')

if [ "$BUILD_NO" = "null" ]; then
    echo "❌ Failed to trigger build:"
    echo "$RESPONSE" | jq .
    exit 1
fi

echo "✅ Build #$BUILD_NO started!"
echo "🔗 View at: $URL"

# --- 轮询模式 ---
if [ "$WATCH_MODE" = true ]; then
    echo "👀 Watching build #$BUILD_NO (polling every 60s)..."
    while true; do
        sleep 60
        INFO=$(curl -s -H "Authorization: Bearer $TOKEN" \
          "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO")
        
        STATE=$(echo "$INFO" | jq -r '.state')
        TIMESTAMP=$(date '+%H:%M:%S')
        
        echo "[$TIMESTAMP] Current State: $STATE"
        
        if [[ "$STATE" != "running" && "$STATE" != "scheduled" ]]; then
            echo "🏁 Build #$BUILD_NO finished with state: $STATE"
            
            if [ "$STATE" = "failed" ]; then
                echo "❌ Fetching failure details..."
                JOB_ID=$(echo "$INFO" | jq -r '.jobs[] | select(.state=="failed") | .id' | head -n 1)
                if [ -n "$JOB_ID" ]; then
                    curl -s -H "Authorization: Bearer $TOKEN" \
                      "https://api.buildkite.com/v2/organizations/$ORG/pipelines/$PIPELINE/builds/$BUILD_NO/jobs/$JOB_ID/log.txt" | tail -n 50
                fi
            fi
            break
        fi
    done
fi
