# services/settings_store.py
import os
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
SET_DEF = os.path.join(CONFIG_DIR, "settings.yaml")
SET_OVR = os.path.join(CONFIG_DIR, "settings.local.yaml")

# Ordner sicherstellen
os.makedirs(CONFIG_DIR, exist_ok=True)

def _get(data: dict, path: str, default=None):
    cur = data or {}
    parts = path.split(".")
    for idx, k in enumerate(parts):
        if not isinstance(cur, dict):
            return default
        remaining = ".".join(parts[idx:])
        if remaining in cur:
            return cur.get(remaining, default)
        cur = cur.get(k)
        if cur is None:
            return default
    return cur

def _ensure(data: dict, path: str):
    cur = data
    for k in path.split("."):
        cur = cur.setdefault(k, {})
    return cur

def get_var(key: str, default=None):
    v = _get(load_yaml(SET_OVR, {}) or {}, f"settings.{key}", None)
    if v is None:
        v = _get(load_yaml(SET_DEF, {}) or {}, f"settings.{key}", None)
    return default if v is None else v


def get_bool(key: str, default: bool = False) -> bool:
    value = get_var(key, None)
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes", "y", "enabled"):
        return True
    if text in ("0", "false", "off", "no", "n", "disabled"):
        return False

    try:
        return float(text) > 0.0
    except Exception:
        return default


def is_orchestrator_enabled() -> bool:
    return get_bool("orchestrator_enabled", True)

def set_vars(**pairs):
    os.makedirs(os.path.dirname(SET_OVR), exist_ok=True)
    ovr = load_yaml(SET_OVR, {}) or {}
    blk = _ensure(ovr, "settings")
    for k, v in pairs.items():
        if v is not None:
            blk[k] = v
    save_yaml(SET_OVR, ovr)
