#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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
set -e
source /etc/profile.d/*.sh

readonly SCRIPT_NAME=$(basename "$0")

show_help() {
cat << EOF
Usage: $SCRIPT_NAME -v VERSION [-P] [-h]

Configure and build openYuanrong documentation.

Options:
  -v VERSION    (Optional) Specify the version string. Defaults to "latest".
  -P            (Optional) Use the installed package instead of building the runtime from source.
  -h            Display this help message and exit.

Examples:
  ./$SCRIPT_NAME -v 1.0.0
  ./$SCRIPT_NAME -v 1.0.0 -P
EOF
}

BUILD_VERSION="latest"
BUILD_WITH_PACKAGE="false"

while getopts "hv:P" opt; do
  case $opt in
    h)
      show_help
      exit 0
      ;;
    v)
      BUILD_VERSION="$OPTARG"
      ;;
    P)
      BUILD_WITH_PACKAGE="true"
      ;;
    \? | :)
      echo "Try '$SCRIPT_NAME -h' for more information." >&2
      exit 1
      ;;
  esac
done

# Export environment variables
export BUILD_VERSION
export BUILD_WITH_PACKAGE

BASE_DIR=$(dirname "$(readlink -f "$0")")
OUTPUT_DIR=${BASE_DIR}/../output

# Add noindex meta tag to all HTML files in a directory (for non-latest versions).
# This prevents Google from indexing outdated documentation.
function add_noindex() {
  local DIR="$1"
  find "$DIR" -name "*.html" -not -path "*/_static/*" -not -path "*/_modules/*" -not -path "*/_sources/*" | while read -r file; do
    if ! grep -q 'name="robots"' "$file"; then
      sed -i 's/<head>/<head>\n    <meta name="robots" content="noindex, nofollow">/' "$file"
    fi
  done
}

function build_zh_cn() {
  pushd "${BASE_DIR}"/source_zh_cn
  make html
  # disable configuration：SPHINXOPTS="-W --keep-going -n", enable it after all alarms are cleared.
  popd

  # modify sphinx built-in search: allow numeric terms in search queries.
  # Sphinx's searchtools.js skips words matching /^\d+$/ (pure digits).
  # The || and queryTerm.match are on separate lines, so we need multiline sed.
  # First join the lines, then remove the digit-match condition.
  sed -i '/||$/{N;s/||\n\s*queryTerm\.match(\/\^\\d+\$\/)//;}' "${BASE_DIR}"/source_zh_cn/_build/html/_static/searchtools.js
  rm -rf "${OUTPUT_DIR}"/docs/zh-cn && mkdir -p "${OUTPUT_DIR}"/docs/zh-cn
  cp -rf "${BASE_DIR}"/source_zh_cn/_build/html/* "${OUTPUT_DIR}"/docs/zh-cn

  if [ "$BUILD_VERSION" = "latest" ]; then
    # sphinx_sitemap does not include html_additional_pages (custom-index.html).
    # Add the homepage index.html to the sitemap manually (inside <urlset>).
    SITEMAP="${OUTPUT_DIR}"/docs/zh-cn/sitemap.xml
    if [ -f "$SITEMAP" ]; then
      BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
      sed -i "/<urlset.*>/a<url><loc>https://docs.openyuanrong.org/zh-cn/${BUILD_VERSION}/index.html</loc><lastmod>${BUILD_DATE}</lastmod></url>" "$SITEMAP"
    fi
  else
    # Non-latest versions should not be indexed by search engines.
    add_noindex "${OUTPUT_DIR}"/docs/zh-cn
    # Remove sitemap so search engines won't discover these pages.
    rm -f "${OUTPUT_DIR}"/docs/zh-cn/sitemap.xml
  fi
}

function build_en() {
  pushd "${BASE_DIR}"/source_en
  make html
  # disable configuration：SPHINXOPTS="-W --keep-going -n", enable it after all alarms are cleared.
  popd

  # modify sphinx built-in search: allow numeric terms in search queries.
  # Sphinx's searchtools.js skips words matching /^\d+$/ (pure digits).
  # The || and queryTerm.match are on separate lines, so we need multiline sed.
  # First join the lines, then remove the digit-match condition.
  sed -i '/||$/{N;s/||\n\s*queryTerm\.match(\/\^\\d+\$\/)//;}' "${BASE_DIR}"/source_en/_build/html/_static/searchtools.js
  rm -rf "${OUTPUT_DIR}"/docs/en && mkdir -p "${OUTPUT_DIR}"/docs/en
  cp -rf "${BASE_DIR}"/source_en/_build/html/* "${OUTPUT_DIR}"/docs/en

  if [ "$BUILD_VERSION" = "latest" ]; then
    # sphinx_sitemap does not include html_additional_pages (custom-index.html).
    # Add the homepage index.html to the sitemap manually (inside <urlset>).
    SITEMAP="${OUTPUT_DIR}"/docs/en/sitemap.xml
    if [ -f "$SITEMAP" ]; then
      BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
      sed -i "/<urlset.*>/a<url><loc>https://docs.openyuanrong.org/en/${BUILD_VERSION}/index.html</loc><lastmod>${BUILD_DATE}</lastmod></url>" "$SITEMAP"
    fi
  else
    # Non-latest versions should not be indexed by search engines.
    add_noindex "${OUTPUT_DIR}"/docs/en
    # Remove sitemap so search engines won't discover these pages.
    rm -f "${OUTPUT_DIR}"/docs/en/sitemap.xml
  fi
}

function generate_sitemap_index() {
  # Generate sitemap index at root level referencing both language sitemaps
  cat > "${OUTPUT_DIR}"/docs/sitemap.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://docs.openyuanrong.org/zh-cn/latest/sitemap.xml</loc>
  </sitemap>
  <sitemap>
    <loc>https://docs.openyuanrong.org/en/latest/sitemap.xml</loc>
  </sitemap>
</sitemapindex>
EOF

  # Generate robots.txt at root level
  cat > "${OUTPUT_DIR}"/docs/robots.txt << 'EOF'
User-agent: *
Allow: /zh-cn/latest/
Allow: /en/latest/
Disallow: /zh-cn/
Disallow: /en/
Disallow: */search.html

Sitemap: https://docs.openyuanrong.org/sitemap.xml
EOF
}

function doc_build() {
  pip install -r "${BASE_DIR}"/requirements_dev.txt
  build_zh_cn
  build_en
  generate_sitemap_index
}

doc_build
