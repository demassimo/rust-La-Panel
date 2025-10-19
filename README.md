# Rust Panel (Flask) — with Auto Install/Update for Rust + Oxide

A tiny Flask web panel to manage a Rust Dedicated Server on Linux.
Features:
- Secure login screen (session cookie, configurable credentials)
- Live console (journalctl -fu) via Server-Sent Events
- Start / Stop / Restart (systemd service)
- **Install Rust** via SteamCMD (first-time bootstrap)
- **Update Rust** via SteamCMD
- **Install/Update Oxide/uMod** from a provided ZIP URL (or Carbon if you supply its URL)
- Optional toggle to auto-run a Rust download before Oxide installs
- Web configuration page to adjust service paths and script settings

## Paths & assumptions
- Steam user: `steam`
- SteamCMD: `/home/steam/steamcmd/steamcmd.sh`
- Rust server dir: `/home/steam/rust-server`
- Systemd service name: `rust-server`

You can change these in the helper scripts under `scripts/`, via the new web configuration page, or with env vars used by the service.

## Install

### 1) Create the helper scripts (as root)
```
install -Dm755 scripts/rust_install.sh /usr/local/bin/rust_install.sh
install -Dm755 scripts/rust_update.sh /usr/local/bin/rust_update.sh
install -Dm755 scripts/oxide_update.sh /usr/local/bin/oxide_update.sh
```

### 2) Sudoers (limit panel privileges)
Allow the `rustpanel` service user to run just these commands without a password:
```
/etc/sudoers.d/rustpanel
---------------------------------------
rustpanel ALL=NOPASSWD: /bin/systemctl start rust-server
rustpanel ALL=NOPASSWD: /bin/systemctl stop rust-server
rustpanel ALL=NOPASSWD: /bin/systemctl restart rust-server
rustpanel ALL=NOPASSWD: /bin/systemctl status rust-server
rustpanel ALL=NOPASSWD: /bin/journalctl -u rust-server
rustpanel ALL=NOPASSWD: /usr/local/bin/rust_install.sh
rustpanel ALL=NOPASSWD: /usr/local/bin/rust_update.sh
rustpanel ALL=NOPASSWD: /usr/local/bin/oxide_update.sh *
---------------------------------------
```

> The `*` after `oxide_update.sh` allows passing a single URL argument.

### 3) Python app
Deploy `app.py` and `templates/index.html` to e.g. `/home/rustpanel/rust-panel/`.
Create a venv and install Flask:
```
sudo -u rustpanel bash -lc '
  cd ~/rust-panel
  python3 -m venv ../venv
  ../venv/bin/pip install --upgrade pip Flask
'
```

### 4) Systemd unit for the panel
```
/etc/systemd/system/rustpanel.service
---------------------------------------
[Unit]
Description=Flask Rust Panel
After=network.target

[Service]
User=rustpanel
WorkingDirectory=/home/rustpanel/rust-panel
Environment=RUST_SERVICE=rust-server
# Optional: override login credentials (defaults admin/rustpanel)
# Environment=RUSTPANEL_USER=rustpanel
# Environment=RUSTPANEL_PASSWORD=ChangeMeNow
# Or provide a pre-hashed password (pbkdf2:sha256)
# Environment=RUSTPANEL_PASSWORD_HASH=...
# Optional auth token for API callers (still works in addition to UI login)
# Environment=RUSTPANEL_TOKEN=YourStrongTokenHere
ExecStart=/home/rustpanel/venv/bin/python /home/rustpanel/rust-panel/app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
---------------------------------------
```
Enable:
```
systemctl daemon-reload
systemctl enable --now rustpanel
```

## Using the panel
- Visit: `http://<container-ip>:8080`
- Log in with the configured credentials (default `admin` / `rustpanel` — change these!).
- Buttons:
  - **Start/Stop/Restart**
  - **Install Rust**: bootstraps/validates the dedicated server with SteamCMD
  - **Update Rust**: runs SteamCMD `+app_update 258550`
  - **Install/Update Oxide**: provide a **direct ZIP URL** and click update

### Getting an Oxide/Carbon ZIP URL
- uMod/Oxide: get a direct Linux build ZIP URL from the uMod site.
- Carbon: copy the link to the Linux build zip from their releases.
Paste that URL into the panel field and run the installer.

## Nightly auto-update (optional)
Add a cron for the `steam` user:
```
sudo -u steam crontab -e
# Example: 04:30 daily
30 4 * * * /usr/local/bin/rust_update.sh >> /home/steam/rust-update.log 2>&1
```
