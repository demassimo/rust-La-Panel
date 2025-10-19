#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="${1:-/opt/rust-panel}"
APP_DIR="${INSTALL_DIR}/app"
CONFIG_DIR="/etc/rust-panel"
ENV_FILE="${CONFIG_DIR}/panel.env"
DEFAULT_SERVICE_NAME="rustpanel"
DEFAULT_RUST_SERVICE="rust-server"

usage() {
  cat <<'USAGE'
Usage: install_panel.sh [INSTALL_DIR]

Interactive installer for the Rust-La-Panel application. Copies the
application into INSTALL_DIR (default: /opt/rust-panel), installs Python
dependencies system-wide, sets up a systemd service, configures sudoers
rules for the panel service user, and installs the helper scripts needed to
manage the Rust server. Run this script as root on Ubuntu.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] This installer must be run as root." >&2
  exit 1
fi

echo "[INFO] Preparing APT repositories for Steam installation..."
export DEBIAN_FRONTEND=noninteractive
if ! dpkg --print-foreign-architectures | grep -qx 'i386'; then
  dpkg --add-architecture i386
fi

apt-get update >/dev/null

if ! command -v add-apt-repository >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends software-properties-common lsb-release >/dev/null
fi

if ! add-apt-repository -yn multiverse >/dev/null; then
  echo "[WARN] Unable to enable the multiverse repository automatically. Please ensure it is enabled." >&2
fi

apt-get update >/dev/null

echo "[INFO] Installing required system packages, including SteamCMD..."
apt-get install -y --no-install-recommends \
  python3 python3-flask python3-dotenv sudo \
  steamcmd lib32gcc-s1 lib32stdc++6 ca-certificates >/dev/null

read -rp "Enter the systemd service name for the panel [${DEFAULT_SERVICE_NAME}]: " input_service
PANEL_SERVICE_NAME="${input_service:-${DEFAULT_SERVICE_NAME}}"
SERVICE_FILE="/etc/systemd/system/${PANEL_SERVICE_NAME}.service"
SUDOERS_FILE="/etc/sudoers.d/${PANEL_SERVICE_NAME}"

read -rp "Enter the Linux user to run the panel service [${PANEL_SERVICE_NAME}]: " input_user
PANEL_SERVICE_USER="${input_user:-${PANEL_SERVICE_NAME}}"

read -rp "Enter the systemd service name that manages the Rust server [${DEFAULT_RUST_SERVICE}]: " input_rust_service
RUST_SERVER_SERVICE="${input_rust_service:-${DEFAULT_RUST_SERVICE}}"

read -rp "Enter the Steam user that owns the Rust server [steam]: " input_steam_user
STEAM_USER="${input_steam_user:-steam}"

default_steam_home="/home/${STEAM_USER}"
read -rp "Enter the Steam home directory [${default_steam_home}]: " input_steam_home
STEAM_HOME="${input_steam_home:-${default_steam_home}}"

default_steamcmd="${STEAM_HOME}/steamcmd/steamcmd.sh"
if command -v steamcmd >/dev/null 2>&1; then
  default_steamcmd="$(command -v steamcmd)"
fi
read -rp "Enter the SteamCMD path [${default_steamcmd}]: " input_steamcmd
STEAMCMD="${input_steamcmd:-${default_steamcmd}}"

default_rust_dir="${STEAM_HOME}/rust-server"
read -rp "Enter the Rust server directory [${default_rust_dir}]: " input_rust_dir
RUST_DIR="${input_rust_dir:-${default_rust_dir}}"

read -rp "Enter the panel login username [admin]: " input_panel_user
PANEL_LOGIN_USER="${input_panel_user:-admin}"

while true; do
  read -srp "Enter the panel login password: " PANEL_LOGIN_PASSWORD
  echo
  read -srp "Confirm the panel login password: " PANEL_LOGIN_PASSWORD_CONFIRM
  echo
  if [[ -z "${PANEL_LOGIN_PASSWORD}" ]]; then
    echo "[WARN] Password cannot be empty. Please try again."
    continue
  fi
  if [[ "${PANEL_LOGIN_PASSWORD}" != "${PANEL_LOGIN_PASSWORD_CONFIRM}" ]]; then
    echo "[WARN] Passwords do not match. Please try again."
    continue
  fi
  break
done

echo "[INFO] Hashing panel password..."
PANEL_PASSWORD_HASH="$(
  PANEL_PASSWORD="${PANEL_LOGIN_PASSWORD}" python3 - <<'PY'
import os
from werkzeug.security import generate_password_hash

password = os.environ["PANEL_PASSWORD"]
print(generate_password_hash(password))
PY
)"
unset PANEL_LOGIN_PASSWORD PANEL_LOGIN_PASSWORD_CONFIRM PANEL_PASSWORD

mkdir -p "${INSTALL_DIR}" "${APP_DIR}" "${CONFIG_DIR}"

if ! id "${PANEL_SERVICE_USER}" >/dev/null 2>&1; then
  echo "[INFO] Creating service user '${PANEL_SERVICE_USER}'."
  useradd --system --create-home --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${PANEL_SERVICE_USER}"
fi

PANEL_SERVICE_GROUP="$(id -gn "${PANEL_SERVICE_USER}")"

copy_path() {
  local source_path="${1}" destination_path="${2}"
  if [[ -d "${source_path}" ]]; then
    rm -rf "${destination_path}"
    mkdir -p "${destination_path}"
    cp -a "${source_path}/." "${destination_path}/"
  else
    install -Dm644 "${source_path}" "${destination_path}"
  fi
}

echo "[INFO] Copying application files to ${APP_DIR}"
copy_path "${REPO_ROOT}/app.py" "${APP_DIR}/app.py"
copy_path "${REPO_ROOT}/templates" "${APP_DIR}/templates"

if [[ -d "${REPO_ROOT}/static" ]]; then
  copy_path "${REPO_ROOT}/static" "${APP_DIR}/static"
fi

install -Dm644 "${REPO_ROOT}/requirements.txt" "${APP_DIR}/requirements.txt"

echo "[INFO] Installing helper scripts into /usr/local/bin"
install -Dm755 "${REPO_ROOT}/scripts/rust_install.sh" /usr/local/bin/rust_install.sh
install -Dm755 "${REPO_ROOT}/scripts/rust_update.sh" /usr/local/bin/rust_update.sh
install -Dm755 "${REPO_ROOT}/scripts/oxide_update.sh" /usr/local/bin/oxide_update.sh

cat >"${ENV_FILE}" <<ENV
# Managed by install_panel.sh
FLASK_ENV=production
RUSTPANEL_USER=${PANEL_LOGIN_USER}
RUSTPANEL_PASSWORD_HASH=${PANEL_PASSWORD_HASH}
RUST_SERVICE=${RUST_SERVER_SERVICE}
STEAM_USER=${STEAM_USER}
STEAM_HOME=${STEAM_HOME}
STEAMCMD=${STEAMCMD}
RUST_DIR=${RUST_DIR}
PANEL_FILE_ROOT=${RUST_DIR}
ENV

chmod 640 "${ENV_FILE}"
chown root:"${PANEL_SERVICE_GROUP}" "${ENV_FILE}"

cat >"${SERVICE_FILE}" <<SERVICE
[Unit]
Description=Rust-La-Panel web interface
After=network.target

[Service]
User=${PANEL_SERVICE_USER}
Group=${PANEL_SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/python3 ${APP_DIR}/app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

chmod 644 "${SERVICE_FILE}"

cat >"${SUDOERS_FILE}" <<SUDOERS
# Managed by install_panel.sh
${PANEL_SERVICE_USER} ALL=NOPASSWD: /bin/systemctl start ${RUST_SERVER_SERVICE}
${PANEL_SERVICE_USER} ALL=NOPASSWD: /bin/systemctl stop ${RUST_SERVER_SERVICE}
${PANEL_SERVICE_USER} ALL=NOPASSWD: /bin/systemctl restart ${RUST_SERVER_SERVICE}
${PANEL_SERVICE_USER} ALL=NOPASSWD: /bin/systemctl status ${RUST_SERVER_SERVICE}
${PANEL_SERVICE_USER} ALL=NOPASSWD: /bin/journalctl -u ${RUST_SERVER_SERVICE}
${PANEL_SERVICE_USER} ALL=NOPASSWD: /usr/local/bin/rust_install.sh
${PANEL_SERVICE_USER} ALL=NOPASSWD: /usr/local/bin/rust_update.sh
${PANEL_SERVICE_USER} ALL=NOPASSWD: /usr/local/bin/oxide_update.sh *
SUDOERS

chmod 440 "${SUDOERS_FILE}"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "${SUDOERS_FILE}" >/dev/null
fi

chown -R "${PANEL_SERVICE_USER}:${PANEL_SERVICE_GROUP}" "${INSTALL_DIR}"

if command -v systemctl >/dev/null 2>&1; then
  echo "[INFO] Enabling and starting ${PANEL_SERVICE_NAME}.service"
  systemctl daemon-reload
  systemctl enable --now "${PANEL_SERVICE_NAME}.service"
else
  echo "[WARN] systemctl not found. Skipping automatic service enable."
fi

cat <<MSG
Rust-La-Panel installed successfully.

- Application directory: ${APP_DIR}
- Service user: ${PANEL_SERVICE_USER}
- Panel service: ${PANEL_SERVICE_NAME}.service
- Rust server service: ${RUST_SERVER_SERVICE}

You can adjust environment settings at ${ENV_FILE}. After any changes run:
  sudo systemctl daemon-reload
  sudo systemctl restart ${PANEL_SERVICE_NAME}.service
MSG
