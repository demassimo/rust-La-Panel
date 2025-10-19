import json
import os, subprocess, contextlib, tarfile, shutil, time
from pathlib import Path
from threading import Lock
from datetime import datetime

from functools import wraps
from flask import Flask, Response, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get("RUSTPANEL_CONFIG_FILE", BASE_DIR / "config.json")).expanduser()

# === CONFIGURATION ===
AUTH_TOKEN = os.environ.get("RUSTPANEL_TOKEN", "")  # optional token

_default_steam_user = os.environ.get("STEAM_USER", "steam")
_default_steam_home = os.environ.get("STEAM_HOME", f"/home/{_default_steam_user}")
_default_steamcmd = os.environ.get("STEAMCMD", f"{_default_steam_home}/steamcmd/steamcmd.sh")
_default_rust_dir = os.environ.get("RUST_DIR", f"{_default_steam_home}/rust-server")
_default_file_root = os.environ.get("PANEL_FILE_ROOT", _default_rust_dir)

DEFAULT_CONFIG = {
    "service": os.environ.get("RUST_SERVICE", "rust-server"),
    "steam_user": _default_steam_user,
    "steam_home": _default_steam_home,
    "steamcmd": _default_steamcmd,
    "rust_dir": _default_rust_dir,
    "file_root": _default_file_root,
    "auto_download_rust_with_oxide": False,
}

_CONFIG_LOCK = Lock()

BACKUP_DIR_NAME = "backups"
_BACKUP_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

def _load_config_file() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key in cfg:
                if key in data:
                    cfg[key] = data[key]
    return cfg

def _persist_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    tmp.replace(CONFIG_FILE)

def _normalize_paths(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} is required")
    if not value.startswith("/"):
        raise ValueError(f"{field} must be an absolute path")
    return str(Path(value).expanduser())

def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

def _update_config(updates: dict) -> dict:
    global CONFIG
    with _CONFIG_LOCK:
        cfg = dict(CONFIG)
        for key, value in updates.items():
            if key not in DEFAULT_CONFIG:
                raise ValueError(f"Unknown setting: {key}")
            if key == "auto_download_rust_with_oxide":
                cfg[key] = _coerce_bool(value)
                continue
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            if key in {"steam_home", "steamcmd", "rust_dir", "file_root"}:
                cfg[key] = _normalize_paths(value, field=key.replace("_", " ").title())
            else:
                value = value.strip()
                if not value:
                    raise ValueError(f"{key.replace('_', ' ').title()} is required")
                cfg[key] = value
        CONFIG = cfg
        _apply_config(CONFIG)
        _persist_config(CONFIG)
        return dict(CONFIG)

def _get_config() -> dict:
    with _CONFIG_LOCK:
        return dict(CONFIG)

def _build_script_env(cfg: dict, file_root: Path) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "RUST_SERVICE": cfg["service"],
            "STEAM_USER": cfg["steam_user"],
            "STEAM_HOME": cfg["steam_home"],
            "STEAMCMD": cfg["steamcmd"],
            "RUST_DIR": cfg["rust_dir"],
            "PANEL_FILE_ROOT": str(file_root),
        }
    )
    return env

def _apply_config(cfg: dict) -> None:
    global SERVICE, STEAM_USER, STEAM_HOME, STEAMCMD, RUST_DIR, FILE_ROOT, SCRIPT_ENV
    SERVICE = cfg["service"]
    STEAM_USER = cfg["steam_user"]
    STEAM_HOME = cfg["steam_home"]
    STEAMCMD = cfg["steamcmd"]
    RUST_DIR = cfg["rust_dir"]
    FILE_ROOT = Path(cfg["file_root"]).expanduser().resolve()
    SCRIPT_ENV = _build_script_env(cfg, FILE_ROOT)


CONFIG = _load_config_file()
SCRIPT_ENV: dict[str, str]
SERVICE = STEAM_USER = STEAM_HOME = STEAMCMD = RUST_DIR = ""
FILE_ROOT = Path(DEFAULT_CONFIG["file_root"]).expanduser().resolve()
_apply_config(CONFIG)

PANEL_USER = os.environ.get("RUSTPANEL_USER", "admin")
_password_hash = os.environ.get("RUSTPANEL_PASSWORD_HASH", "")
if _password_hash:
    PANEL_PASSWORD_HASH = _password_hash
else:
    PANEL_PASSWORD_HASH = generate_password_hash(os.environ.get("RUSTPANEL_PASSWORD", "rustpanel"))

SECRET = os.environ.get("RUSTPANEL_SECRET") or os.environ.get("SECRET_KEY") or os.urandom(32)

# --- Flask setup (define template path manually) ---
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
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
    p = subprocess.run(cmd, capture_output=True, text=True, env=SCRIPT_ENV)
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
    cfg = _get_config()
    return render_template(
        "index.html",
        service=cfg["service"],
        token_set=bool(AUTH_TOKEN),
        file_root=str(FILE_ROOT),
        auto_download=cfg["auto_download_rust_with_oxide"],
        backups_path='/' + BACKUP_DIR_NAME,
    )


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


@app.route("/config", methods=["GET", "POST"])
@_login_required
def config_page():
    message = None
    error = None
    cfg = _get_config()

    if request.method == "POST":
        updates = {
            "service": request.form.get("service", ""),
            "steam_user": request.form.get("steam_user", ""),
            "steam_home": request.form.get("steam_home", ""),
            "steamcmd": request.form.get("steamcmd", ""),
            "rust_dir": request.form.get("rust_dir", ""),
            "file_root": request.form.get("file_root", ""),
            "auto_download_rust_with_oxide": request.form.get("auto_download_rust_with_oxide", "off"),
        }
        try:
            cfg = _update_config(updates)
            message = "Configuration saved."
        except ValueError as exc:
            error = str(exc)
            cfg.update({k: v for k, v in updates.items() if k in cfg and k != "auto_download_rust_with_oxide"})
            cfg["auto_download_rust_with_oxide"] = _coerce_bool(updates.get("auto_download_rust_with_oxide", False))

    return render_template("config.html", config=cfg, message=message, error=error, config_path=str(CONFIG_FILE))


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

    cfg = _get_config()
    steps = []
    if cfg.get("auto_download_rust_with_oxide"):
        rust_code, rust_out = _run(["sudo", "/usr/local/bin/rust_update.sh"])
        steps.append(("Rust update", rust_code, rust_out))
        if rust_code != 0:
            combined = "\n\n".join(f"{name} exit {code}: {text}".strip() for name, code, text in steps)
            return jsonify({"ok": False, "exit": rust_code, "output": combined})

    code, out = _run(["sudo", "/usr/local/bin/oxide_update.sh", url])
    steps.append(("Oxide update", code, out))
    combined = "\n\n".join(f"{name} exit {code}: {text}".strip() for name, code, text in steps)
    return jsonify({"ok": code == 0 and all(step[1] == 0 for step in steps), "exit": code, "output": combined})


@app.get("/api/config")
def api_get_config():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify({"ok": True, "config": _get_config()})


@app.post("/api/config")
def api_update_config():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    try:
        cfg = _update_config(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "config": cfg})


@app.get("/api/metrics")
def api_metrics():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0

    metrics = {
        "ok": True,
        "load": {"1": load1, "5": load5, "15": load15},
        "memory": _memory_usage(),
        "disk": _disk_usage(FILE_ROOT),
    }
    return jsonify(metrics)


@app.get("/api/backups")
def api_list_backups():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    backups = _list_backups()
    return jsonify({"ok": True, "backups": backups, "path": _relative(_ensure_backup_dir())})


@app.post("/api/backups")
def api_create_backup():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    label = data.get("label") if isinstance(data, dict) else None
    backup_dir = _ensure_backup_dir()
    name = _new_backup_name(label if isinstance(label, str) else None)
    target = backup_dir / name
    counter = 1
    while target.exists():
        target = backup_dir / f"{name[:-7]}-{counter}.tar.gz"
        counter += 1

    try:
        _create_backup_archive(target)
        created = time.time()
        stat = target.stat()
    except (OSError, tarfile.TarError) as exc:
        with contextlib.suppress(OSError):
            if target.exists():
                target.unlink()
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "backup": {
                "name": target.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "created": created,
            },
        }
    )


@app.delete("/api/backups/<name>")
def api_delete_backup(name: str):
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        path = _backup_file_path(name)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid name"}), 400

    if not path.exists() or not path.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404

    try:
        path.unlink()
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})

# --- File manager ---
BANNED_EXTS = {".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
".dds", ".tga", ".psd", ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".avi", ".mov", ".mkv", ".pak",
".bin", ".dat"
}

def _memory_usage() -> dict:
    total = available = used = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as fh:
            data = {}
            for line in fh:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                parts = value.strip().split()
                if not parts:
                    continue
                data[key] = int(parts[0]) * 1024  # values are in kB
        total = data.get("MemTotal", 0)
        available = data.get("MemAvailable", data.get("MemFree", 0))
        used = total - available if total and available else 0
    except OSError:
        pass
    percent = (used / total * 100) if total else 0
    return {"total": total, "used": used, "available": available, "percent": percent}


def _disk_usage(root: Path) -> dict:
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return {"total": 0, "used": 0, "free": 0, "percent": 0}
    used = usage.total - usage.free
    percent = (used / usage.total * 100) if usage.total else 0
    return {"total": usage.total, "used": used, "free": usage.free, "percent": percent}


def _ensure_backup_dir() -> Path:
    target = _safe_path(BACKUP_DIR_NAME)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _backup_file_path(name: str) -> Path:
    if not name or any(ch not in _BACKUP_ALLOWED for ch in name):
        raise ValueError("invalid name")
    if not name.endswith(".tar.gz"):
        raise ValueError("invalid name")
    return _safe_path(f"{BACKUP_DIR_NAME}/{name}")


def _sanitize_backup_slug(label: str | None) -> str:
    if not label:
        return ""
    slug = "".join(ch for ch in label if ch in _BACKUP_ALLOWED and ch not in {"."})
    return slug.strip("-_")[:48]


def _new_backup_name(label: str | None = None) -> str:
    base = datetime.utcnow().strftime("backup-%Y%m%d-%H%M%S")
    slug = _sanitize_backup_slug(label)
    if slug:
        base = f"{base}-{slug}"
    return f"{base}.tar.gz"


def _create_backup_archive(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = [p for p in Path(info.name).parts if p not in {"."}]
        if parts and parts[0] == BACKUP_DIR_NAME:
            return None
        return info

    with tarfile.open(destination, "w:gz") as tar:
        tar.add(FILE_ROOT, arcname=".", filter=_filter)


def _list_backups() -> list[dict]:
    backup_dir = _ensure_backup_dir()
    backups = []
    try:
        entries = sorted(backup_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return backups

    for path in entries:
        try:
            stat = path.stat()
        except OSError:
            continue
        backups.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return backups

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
