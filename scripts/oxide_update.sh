#!/bin/bash
# oxide_update.sh — usage: oxide_update.sh <DIRECT_ZIP_URL>
# Downloads a Linux Oxide/Carbon ZIP and extracts into the Rust server dir.
set -euo pipefail
if [ $# -lt 1 ]; then
  echo "Usage: $0 <DIRECT_ZIP_URL>"
  exit 2
fi
ZIP_URL="$1"
STEAM_USER="${STEAM_USER:-steam}"
STEAM_HOME="${STEAM_HOME:-/home/${STEAM_USER}}"
RUST_DIR="${RUST_DIR:-${STEAM_HOME}/rust-server}"

TMP_ZIP="/tmp/oxide_update.zip"
echo "Downloading: ${ZIP_URL}"
curl -fsSL "${ZIP_URL}" -o "${TMP_ZIP}"
echo "Extracting into ${RUST_DIR} ..."
# Ensure unzip exists
if ! command -v unzip >/dev/null 2>&1; then
  apt-get update && apt-get install -y unzip
fi
# Extract as steam user to keep ownership sane
chown "${STEAM_USER}:${STEAM_USER}" "${TMP_ZIP}"
sudo -u "${STEAM_USER}" bash -lc "unzip -o ${TMP_ZIP} -d \"${RUST_DIR}\""
rm -f "${TMP_ZIP}"
echo "Oxide update complete."
