import os, subprocess, contextlib
from pathlib import Path

from functools import wraps
from flask import Flask, Response, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash

# === CONFIGURATION ===
SERVICE = os.environ.get("RUST_SERVICE", "rust-server")
AUTH_TOKEN = os.environ.get("RUSTPANEL_TOKEN", "")  # optional token

# Optional overrides for your setup
STEAM_USER = os.environ.get("STEAM_USER", "steam")
STEAM_HOME = os.environ.get("STEAM_HOME", f"/home/{STEAM_USER}")
STEAMCMD = os.environ.get("STEAMCMD", f"{STEAM_HOME}/steamcmd/steamcmd.sh")
RUST_DIR  = os.environ.get("RUST_DIR",  f"{STEAM_HOME}/rust-server")
FILE_ROOT = Path(os.environ.get("PANEL_FILE_ROOT", RUST_DIR)).resolve()

PANEL_USER = os.environ.get("RUSTPANEL_USER", "admin")
_password_hash = os.environ.get("RUSTPANEL_PASSWORD_HASH", "")
if _password_hash:
    PANEL_PASSWORD_HASH = _password_hash
else:
    PANEL_PASSWORD_HASH = generate_password_hash(os.environ.get("RUSTPANEL_PASSWORD", "rustpanel"))

SECRET = os.environ.get("RUSTPANEL_SECRET") or os.environ.get("SECRET_KEY") or os.urandom(32)

# --- Flask setup (define template path manually) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = SECRET
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# === HELPERS ===
def _authorized(req):
    """Check session login or token header"""
    if session.get("rp_auth"):
        return True
    if AUTH_TOKEN and req.headers.get("X-Auth-Token") == AUTH_TOKEN:
        return True
    return False

def _login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("rp_auth"):
            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))
        return view(*args, **kwargs)
    return wrapped

def _run(cmd: list[str]):
    """Run shell command and return (code, output)"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr or "").strip()

def _safe_path(rel: str) -> Path:
    """Return a safe absolute path within FILE_ROOT."""
    candidate = (FILE_ROOT / rel).resolve()
    if FILE_ROOT not in candidate.parents and candidate != FILE_ROOT:
        raise ValueError("invalid path")
    return candidate

def _relative(path: Path) -> str:
    rel = str(path.relative_to(FILE_ROOT))
    return "" if rel == "." else rel

def _list_entries(path: Path):
    entries = []
    with os.scandir(path) as it:
        entries_iter = sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        for entry in entries_iter:
            is_dir = entry.is_dir(follow_symlinks=False)
            info = {
                "name": entry.name,
                "is_dir": is_dir,
            }
            if not is_dir and entry.is_file(follow_symlinks=False):
                try:
                    info["size"] = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    info["size"] = None
            entries.append(info)
    return entries

# === ROUTES ===
@app.route("/")
@_login_required
def index():
    return render_template(
        "index.html",
        service=SERVICE,
        token_set=bool(AUTH_TOKEN),
        file_root=str(FILE_ROOT),
    )

    return render_template("index.html", service=SERVICE)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("rp_auth"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if username != PANEL_USER or not check_password_hash(PANEL_PASSWORD_HASH, password):
            error = "Invalid username or password"
        else:
            session["rp_auth"] = True
            session.permanent = True
            target = request.args.get("next")
            return redirect(target or url_for("index"))

    return render_template("login.html", error=error)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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


@app.post("/api/install_rust")
def install_rust():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    code, out = _run(["sudo", "/usr/local/bin/rust_install.sh"])
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

# --- File manager ---
BANNED_EXTS = {".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
".dds", ".tga", ".psd", ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".avi", ".mov", ".mkv", ".pak",
".bin", ".dat"
}

@app.get("/api/fs/list")
def fs_list():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    rel = request.args.get("path", "").strip()
    try:
        target = _safe_path(rel or ".")
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not target.exists() or not target.is_dir():
        return jsonify({"ok": False, "error": "not found"}), 404

    try:
        entries = _list_entries(target)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    relative = _relative(target) if target != FILE_ROOT else ""
    parent = _relative(target.parent) if target != FILE_ROOT else None
    return jsonify({"ok": True, "path": relative, "parent": parent, "entries": entries})

def _blocked_extension(path: Path) -> bool:
    return path.suffix.lower() in BANNED_EXTS

def _read_text_file(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return fh.read()

@app.get("/api/fs/file")
def fs_get_file():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    rel = request.args.get("path", "").strip()
    if not rel:
        return jsonify({"ok": False, "error": "missing path"}), 400

    try:
        target = _safe_path(rel)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not target.exists() or not target.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404

    if _blocked_extension(target):
        return jsonify({"ok": False, "error": "binary file"}), 400

    if target.stat().st_size > 2 * 1024 * 1024:  # 2 MB limit
        return jsonify({"ok": False, "error": "file too large"}), 400

    return jsonify({"ok": True, "content": _read_text_file(target)})

@app.post("/api/fs/file")
def fs_save_file():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    rel = data.get("path", "").strip()
    content = data.get("content")

    if not rel or content is None:
        return jsonify({"ok": False, "error": "missing path or content"}), 400

    try:
        target = _safe_path(rel)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if _blocked_extension(target):
        return jsonify({"ok": False, "error": "binary file"}), 400

    if not target.exists() or not target.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404

    try:
        with target.open("w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})

# === RUN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
