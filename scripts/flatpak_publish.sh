#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="${ROOT_DIR}/repo"

if [ ! -d "${REPO_DIR}" ]; then
  "${ROOT_DIR}/scripts/flatpak_build.sh"
fi

flatpak build-update-repo --prune --generate-static-deltas "${REPO_DIR}"

if [ "${1:-}" != "" ]; then
  TARGET_PATH="$1"
  if ! command -v rsync >/dev/null 2>&1; then
    printf "rsync is required when a publish target is provided.\n" >&2
    exit 1
  fi
  rsync -av --delete "${REPO_DIR}/" "${TARGET_PATH}"
  printf "Published repo to %s\n" "${TARGET_PATH}"
else
  printf "Repo updated in place: %s\n" "${REPO_DIR}"
fi
