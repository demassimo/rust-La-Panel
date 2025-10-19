#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="${1:-/opt/rust-panel}"
APP_DIR="${INSTALL_DIR}/app"
VENV_DIR="${INSTALL_DIR}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'USAGE'
Usage: install_panel.sh [INSTALL_DIR]

Installs the Rust-La-Panel application into INSTALL_DIR (default: /opt/rust-panel)
and copies the helper scripts into /usr/local/bin. Requires Python 3 and pip.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[ERROR] Python interpreter '${PYTHON_BIN}' not found." >&2
  exit 1
fi

mkdir -p "${APP_DIR}"

copy_path() {
  local source_path="${1}" destination_path="${2}"
  if [[ -d "${source_path}" ]]; then
    rm -rf "${destination_path}"
    mkdir -p "${destination_path}"
    cp -a "${source_path}/." "${destination_path}/"
  else
    cp -a "${source_path}" "${destination_path}"
  fi
}

copy_path "${REPO_ROOT}/app.py" "${APP_DIR}/app.py"
copy_path "${REPO_ROOT}/templates" "${APP_DIR}/templates"
copy_path "${REPO_ROOT}/.env" "${APP_DIR}/.env"
copy_path "${REPO_ROOT}/requirements.txt" "${APP_DIR}/requirements.txt"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Installing helper scripts into /usr/local/bin"
  install -Dm755 "${REPO_ROOT}/scripts/rust_install.sh" /usr/local/bin/rust_install.sh
  install -Dm755 "${REPO_ROOT}/scripts/rust_update.sh" /usr/local/bin/rust_update.sh
  install -Dm755 "${REPO_ROOT}/scripts/oxide_update.sh" /usr/local/bin/oxide_update.sh
else
  cat <<'MSG'
[INFO] Run this script as root (or re-run with sudo) to install the helper scripts
into /usr/local/bin. They remain available under scripts/ in the repository.
MSG
fi

cat <<MSG
Rust-La-Panel installed into: ${INSTALL_DIR}
Python virtual environment: ${VENV_DIR}

To run the application manually:
  ${VENV_DIR}/bin/python ${APP_DIR}/app.py

For systemd integration, create a unit similar to the example in README.md with:
  ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/app.py
MSG
