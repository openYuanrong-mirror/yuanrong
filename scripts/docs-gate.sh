#!/bin/bash
# Documentation Gate Script
# 本地运行文档门禁检查，与 CI 保持一致

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== 文档门禁检查 ==="
echo ""

# 检查 npm
if ! command -v npx &> /dev/null; then
    echo "错误: npx 未安装"
    exit 1
fi

cd "$REPO_DIR"

# 检查 docs/features 目录
if [ ! -d "docs/features" ]; then
    echo "错误: docs/features 目录不存在"
    exit 1
fi

# CI 配置: https://raw.gitcode.com/openeuler/docs/raw/stable-common/.doctools/markdownlint.config.json
# 本地额外禁用 MD060（版本差异）
CONFIG_FILE=$(mktemp)
cat > "$CONFIG_FILE" << 'EOF'
{
  "default": true,
  "MD003": {
    "style": "atx"
  },
  "MD029": {
    "style": "ordered"
  },
  "MD004": false,
  "MD007": false,
  "MD009": false,
  "MD013": false,
  "MD014": false,
  "MD020": false,
  "MD021": false,
  "MD024": false,
  "MD025": false,
  "MD033": false,
  "MD036": false,
  "MD042": false,
  "MD043": false,
  "MD044": false,
  "MD045": false,
  "MD046": false,
  "MD048": false,
  "MD049": false,
  "MD050": false,
  "MD051": false,
  "MD052": false,
  "MD053": false,
  "MD055": false,
  "MD056": false,
  "MD057": false,
  "MD060": false
}
EOF

# 运行 markdownlint
echo "运行 markdownlint 检查..."
echo ""

ERRORS=$(npx markdownlint docs/features/ --config "$CONFIG_FILE" 2>&1) || true
rm -f "$CONFIG_FILE"

if [ -n "$ERRORS" ]; then
    echo "❌ 文档门禁未通过！"
    echo ""
    echo "$ERRORS"
    echo ""
    echo "请修复上述错误后重新提交"
    exit 1
else
    echo "✅ 文档门禁检查通过"
    exit 0
fi
