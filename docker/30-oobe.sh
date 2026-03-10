#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"
MARKER_FILE="${DATA_DIR}/.oobe-complete"

if [ -f "${MARKER_FILE}" ]; then
  echo "[oobe] OOBE marker already present, skipping OOBE hint."
  exit 0
fi

echo "[oobe] First run detected. Complete the web OOBE in your browser."
echo "[oobe] After initial setup, this marker will be created."

touch "${MARKER_FILE}"

