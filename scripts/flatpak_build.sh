#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT_DIR}/io.github.zyragames.shelldeck.yml"
BUILD_DIR="${ROOT_DIR}/build-dir"
REPO_DIR="${ROOT_DIR}/repo"
LOG_DIR="${ROOT_DIR}/build_logs"
APP_ID="io.github.zyragames.shelldeck"
BRANCH="${FLATPAK_BRANCH:-stable}"
BUNDLE_NAME="${FLATPAK_BUNDLE_NAME:-ShellDeck.flatpak}"

if ! command -v flatpak-builder >/dev/null 2>&1; then
  printf "flatpak-builder is required. Install your distro package first.\n" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

BUILD_LOG="${LOG_DIR}/flatpak-build-$(date +%Y%m%d-%H%M%S).log"
BUNDLE_LOG="${LOG_DIR}/flatpak-bundle-$(date +%Y%m%d-%H%M%S).log"

flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo >/dev/null 2>&1 || true

flatpak-builder \
  --force-clean \
  --install-deps-from=flathub \
  --repo="${REPO_DIR}" \
  "${BUILD_DIR}" \
  "${MANIFEST}" \
  2>&1 | tee "${BUILD_LOG}"

flatpak build-bundle \
  "${REPO_DIR}" \
  "${ROOT_DIR}/${BUNDLE_NAME}" \
  "${APP_ID}" \
  "${BRANCH}" \
  2>&1 | tee "${BUNDLE_LOG}"

printf "Built bundle: %s\n" "${ROOT_DIR}/${BUNDLE_NAME}"
