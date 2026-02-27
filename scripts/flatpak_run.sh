#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="${ROOT_DIR}/repo"
APP_ID="io.github.zyragames.shelldeck"
BRANCH="${FLATPAK_BRANCH:-stable}"
REMOTE_NAME="shelldeck-local"

if [ ! -d "${REPO_DIR}" ]; then
  "${ROOT_DIR}/scripts/flatpak_build.sh"
fi

flatpak --user remote-add --if-not-exists --no-gpg-verify "${REMOTE_NAME}" "file://${REPO_DIR}"
flatpak --user install -y --reinstall "${REMOTE_NAME}" "${APP_ID}//${BRANCH}"
flatpak run "${APP_ID}"
