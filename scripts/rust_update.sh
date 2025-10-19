#!/bin/bash
# rust_update.sh — run as root via sudoers; drops to steam user and runs SteamCMD update
set -euo pipefail
STEAM_USER="${STEAM_USER:-steam}"
STEAM_HOME="${STEAM_HOME:-/home/${STEAM_USER}}"
STEAMCMD="${STEAMCMD:-${STEAM_HOME}/steamcmd/steamcmd.sh}"
INSTALL_DIR="${RUST_DIR:-${STEAM_HOME}/rust-server}"

if [ ! -x "${STEAMCMD}" ]; then
  echo "SteamCMD not found at ${STEAMCMD}. Installing to ${STEAM_HOME}/steamcmd ..."
  sudo -u "${STEAM_USER}" bash -lc "mkdir -p ${STEAM_HOME}/steamcmd && cd ${STEAM_HOME}/steamcmd && wget -q https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz && tar -xzf steamcmd_linux.tar.gz"
fi

echo "Updating Rust server with SteamCMD ..."
sudo -u "${STEAM_USER}" bash -lc ""${STEAMCMD}" +login anonymous +force_install_dir \"${INSTALL_DIR}\" +app_update 258550 validate +quit"
echo "Done."
