import os, subprocess, contextlib
from flask import Flask, Response, request, jsonify, render_template

# === CONFIGURATION ===
SERVICE = os.environ.get("RUST_SERVICE", "rust-server")
AUTH_TOKEN = os.environ.get("RUSTPANEL_TOKEN", "")  # optional token

# Optional overrides for your setup
STEAM_USER = os.environ.get("STEAM_USER", "steam")
STEAM_HOME = os.environ.get("STEAM_HOME", f"/home/{STEAM_USER}")
STEAMCMD = os.environ.get("STEAMCMD", f"{STEAM_HOME}/steamcmd/steamcmd.sh")
RUST_DIR  = os.environ.get("RUST_DIR",  f"{STEAM_HOME}/rust-server")

# --- Flask setup (define template path manually) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# === HELPERS ===
def _authorized(req):
    """Check token if set"""
    if not AUTH_TOKEN:
        return True
    return req.headers.get("X-Auth-Token") == AUTH_TOKEN

def _run(cmd: list[str]):
    """Run shell command and return (code, output)"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr or "").strip()

# === ROUTES ===
@app.route("/")
def index():
    return render_template("index.html", service=SERVICE, token_set=bool(AUTH_TOKEN))

# --- Basic systemd control ---
@app.get("/api/status")
def status():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    code, out = _run(["sudo", "systemctl", "status", SERVICE, "--no-pager"])
    return jsonify({"ok": code == 0, "exit": code, "output": out})

@app.post("/api/<action>")
def action(action: str):
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if action not in {"start", "stop", "restart"}:
        return jsonify({"ok": False, "error": "invalid action"}), 400
    code, out = _run(["sudo", "systemctl", action, SERVICE])
    return jsonify({"ok": code == 0, "exit": code, "output": out})

# --- Live logs (Server-Sent Events) ---
@app.get("/api/logs")
def logs():
    if not _authorized(request):
        return Response("unauthorized\n", status=401)

    n = request.args.get("n", "200")
    since = request.args.get("since", "")
    args = ["sudo", "journalctl", "-u", SERVICE, "--no-pager", "-n", n]
    if since:
        args += ["--since", since]
    args.append("-f")

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def stream():
        try:
            for line in proc.stdout:
                yield f"data: {line.rstrip()}\n\n"
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()

    return Response(stream(), mimetype="text/event-stream")

# --- Rust auto-update (via SteamCMD) ---
@app.post("/api/update_rust")
def update_rust():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    code, out = _run(["sudo", "/usr/local/bin/rust_update.sh"])
    return jsonify({"ok": code == 0, "exit": code, "output": out})

# --- Oxide/uMod/Carbon installer ---
@app.post("/api/update_oxide")
def update_oxide():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "missing url"}), 400

    code, out = _run(["sudo", "/usr/local/bin/oxide_update.sh", url])
    return jsonify({"ok": code == 0, "exit": code, "output": out})

# === RUN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
