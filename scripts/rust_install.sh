#!/bin/bash
# rust_install.sh — bootstrap a brand new Rust Dedicated Server install via SteamCMD.
set -euo pipefail

STEAM_USER="${STEAM_USER:-steam}"
STEAM_HOME="${STEAM_HOME:-/home/${STEAM_USER}}"
STEAMCMD="${STEAMCMD:-${STEAM_HOME}/steamcmd/steamcmd.sh}"
INSTALL_DIR="${RUST_DIR:-${STEAM_HOME}/rust-server}"

if ! id "${STEAM_USER}" >/dev/null 2>&1; then
  echo "Steam user ${STEAM_USER} does not exist. Please create it before running this script." >&2
  exit 1
fi

echo "Installing prerequisites for Rust server ..."
apt-get update >/dev/null
apt-get install -y --no-install-recommends ca-certificates curl wget tar lib32gcc-s1 lib32stdc++6 unzip >/dev/null

if [ ! -x "${STEAMCMD}" ]; then
  echo "SteamCMD not found at ${STEAMCMD}. Installing ..."
  sudo -u "${STEAM_USER}" bash -lc "mkdir -p ${STEAM_HOME}/steamcmd && cd ${STEAM_HOME}/steamcmd && wget -q https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz && tar -xzf steamcmd_linux.tar.gz"
fi

echo "Creating install directory ${INSTALL_DIR} ..."
mkdir -p "${INSTALL_DIR}"
chown -R "${STEAM_USER}:${STEAM_USER}" "${INSTALL_DIR}"

echo "Running initial Rust Dedicated Server install ..."
sudo -u "${STEAM_USER}" bash -lc ""${STEAMCMD}" +login anonymous +force_install_dir \"${INSTALL_DIR}\" +app_update 258550 validate +quit"

echo "Rust Dedicated Server installed at ${INSTALL_DIR}."
