#!/usr/bin/env bash
# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pip uninstall openyuanrong openyuanrong_sdk -y
pip install "${SCRIPT_DIR}/../../output/openyuanrong"*.whl
yr stop
bash "${SCRIPT_DIR}/start_yr_http.sh"
