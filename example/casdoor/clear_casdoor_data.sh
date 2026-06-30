#!/bin/bash

# Casdoor Data Cleanup Script for Yuanrong
# This script stops containers, removes persistent data, and restarts everything.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CASDOOR_DIR="${SCRIPT_DIR}"

echo "==== Step 1: Stopping Casdoor Containers ===="
cd "${CASDOOR_DIR}"
docker-compose down

echo "==== Step 2: Removing Persistent Data ===="
# Use sudo because the postgres data directory might be owned by root
if [ -d "${CASDOOR_DIR}/data/postgres" ]; then
    echo "Removing ${CASDOOR_DIR}/data/postgres..."
    sudo rm -rf "${CASDOOR_DIR}/data/postgres"
fi

echo "==== Step 3: Restarting Casdoor (Fresh State) ===="
docker-compose up -d

echo "Waiting for Casdoor to be ready..."
until curl -s http://localhost:8000 > /dev/null; do
  sleep 2
  echo -n "."
done
echo -e "\nCasdoor is UP and FRESH at http://localhost:8000"
