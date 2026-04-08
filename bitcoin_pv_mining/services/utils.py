# utils_config.py
import os, json, yaml, uuid, datetime as dt, threading

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _normalize_config_dir(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    if os.path.basename(raw.rstrip("/\\")).lower() == "pv_mining_addon":
        return raw
    return os.path.join(raw, "pv_mining_addon")


def _resolve_config_dir() -> str:
    env_candidates = [
        _normalize_config_dir(os.getenv("PV_MINING_CONFIG_DIR", "")),
        _normalize_config_dir(os.getenv("CONFIG_DIR", "")),
    ]
    for path in env_candidates:
        if path:
            return path

    if os.path.isdir("/config"):
        return "/config/pv_mining_addon"

    local_candidate = os.path.join(ADDON_ROOT, "config", "pv_mining_addon")
    if os.path.isdir(local_candidate):
        return local_candidate

    return "/config/pv_mining_addon" if os.path.exists("/config") else local_candidate


CONFIG_DIR = _resolve_config_dir()
SENSORS_PATH = os.path.join(CONFIG_DIR, "sensors.yaml")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")
_STATE_LOCK = threading.RLock()


def _default_state() -> dict:
    return {
        "install_id": str(uuid.uuid4()),
        "sponsor_token": "",
        "premium_enabled": False,
        "lease_expires_at": None,
        "last_heartbeat_at": None,
    }

def load_yaml(path: str, default=None):
    """Lädt YAML und gibt default zurück, falls nicht vorhanden."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except Exception:
        return default

def save_yaml(path, data):
    """
    Speichert ein Python-Objekt (z.B. dict) als YAML.
    Erstellt Ordner bei Bedarf automatisch.
    """
    import os
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"[ERROR] Could not save YAML to {path}: {e}")

def load_sensors():
    return load_yaml(SENSORS_PATH, {"entities": {}})

def load_state():
    with _STATE_LOCK:
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            st = _default_state()
            save_state(st)
            return st

def save_state(st):
    with _STATE_LOCK:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)


def update_state(mutator):
    with _STATE_LOCK:
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = _default_state()

        result = mutator(state)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return state, result

def iso_now():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def get_addon_version(default: str = "0.0.0") -> str:
    """
    Liest die Add-on-Version aus /app/config.yaml (Add-on Root).
    Fallback auf default, wenn Datei fehlt/ungültig.
    """
    path = "/app/config.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return str(cfg.get("version", default))
    except Exception:
        return default
