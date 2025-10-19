#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/demassimo/rust-La-Panel.git"
TARGET_DIR="${1:-/opt/rust-la-panel}"

usage() {
  cat <<'USAGE'
Usage: pull_panel.sh [TARGET_DIR]

Clones or updates the Rust-La-Panel repository into TARGET_DIR
(default: /opt/rust-la-panel).
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo "[ERROR] git is not installed or not in PATH." >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"

if [[ -d "${TARGET_DIR}/.git" ]]; then
  echo "Updating existing repository at ${TARGET_DIR} ..."
  git -C "${TARGET_DIR}" fetch --all
  git -C "${TARGET_DIR}" reset --hard origin/main
else
  if [[ -n "$(ls -A "${TARGET_DIR}" 2>/dev/null)" ]]; then
    echo "[ERROR] Target directory ${TARGET_DIR} is not empty and is not a git repository." >&2
    exit 1
  fi
  echo "Cloning Rust-La-Panel into ${TARGET_DIR} ..."
  git clone "${REPO_URL}" "${TARGET_DIR}"
fi

echo "Repository available at ${TARGET_DIR}".
