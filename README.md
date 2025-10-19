# Rust Panel (Flask) — with Auto Install/Update for Rust + Oxide

A tiny Flask web panel to manage a Rust Dedicated Server on Linux.
Features:
- Secure login screen (session cookie, configurable credentials)
- Live console (journalctl -fu) via Server-Sent Events
- Start / Stop / Restart (systemd service)
- **Install Rust** via SteamCMD (first-time bootstrap)
- **Update Rust** via SteamCMD
- **Install/Update Oxide/uMod** from a provided ZIP URL (or Carbon if you supply its URL) — prefilled with the latest Linux build
- Optional toggle to auto-run a Rust download before Oxide installs
- Web configuration page to adjust service paths and script settings

## Paths & assumptions
- Steam user: `steam`
- SteamCMD: `/home/steam/steamcmd/steamcmd.sh`
- Rust server dir: `/home/steam/rust-server`
- Systemd service name: `rust-server`

You can change these in the helper scripts under `scripts/`, via the new web configuration page, or with env vars used by the service.

## Install

### Automated Ubuntu install (recommended)

Run the interactive installer as root. It will ask for the panel service user,
Rust service name, Steam account paths, and the initial web login credentials.
The script enables the multiverse repository, installs SteamCMD and the 32-bit
runtime libraries it needs, installs the required Python packages system-wide,
copies the web application into `/opt/rust-panel/app` (by default), configures
sudo rules for the panel user, installs the helper scripts into
`/usr/local/bin`, and enables a `systemd` service so the panel starts
automatically.

```
sudo ./scripts/install_panel.sh
```

After the prompts complete you can visit the panel on port 8080 immediately.
All environment settings are stored in `/etc/rust-panel/panel.env`; edit that
file and restart the `rustpanel` service if you ever need to change the
defaults.

### Manual install (advanced)

If you would like to perform the setup yourself, follow the high level steps
below as a reference:

1. Copy the helper scripts from `scripts/` into `/usr/local/bin` and make them
   executable.
2. Grant the panel service user password-less sudo access to the helper scripts
   and to the `systemctl`/`journalctl` commands for your Rust server unit.
3. Deploy the Flask app somewhere (for example `/opt/rust-panel/app.py` and the
   `templates/` directory) and install the Python dependencies globally.
4. Create a `systemd` unit that launches `/usr/bin/python3 /path/to/app.py` with
   the appropriate environment variables for credentials and paths.
5. Enable and start the unit.

The automated installer performs these steps for you using safe defaults.

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
The panel now pre-populates the Oxide field with the latest Linux build from GitHub, so you can simply click install to grab the newest release. Paste a different URL if you need a specific build.

## Nightly auto-update (optional)
Add a cron for the `steam` user:
```
sudo -u steam crontab -e
# Example: 04:30 daily
30 4 * * * /usr/local/bin/rust_update.sh >> /home/steam/rust-update.log 2>&1
```
