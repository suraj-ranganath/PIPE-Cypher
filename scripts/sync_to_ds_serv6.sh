#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-suraj@ds-serv6.ucsd.edu}"
REMOTE_DIR="${REMOTE_DIR:-/home/suraj/PIPE-Cypher}"

rsync -az --delete \
  --exclude '.git/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude 'artifacts/' \
  --exclude 'external/' \
  --exclude 'models/' \
  --exclude 'data/' \
  ./ "${HOST}:${REMOTE_DIR}/"

echo "synced ${PWD} to ${HOST}:${REMOTE_DIR}"
