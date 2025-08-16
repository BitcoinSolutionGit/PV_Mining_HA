# services/settings_store.py
import os
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
SET_DEF = os.path.join(CONFIG_DIR, "settings.yaml")
SET_OVR = os.path.join(CONFIG_DIR, "settings.local.yaml")

os.makedirs(CONFIG_DIR, exist_ok=True)

def _get(data: dict, path: str, default=None):
    cur = data or {}
    for k in path.split("."):
        if not isinstance(cur, dict): return default
        cur = cur.get(k)
        if cur is None: return default
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

def set_vars(**pairs):
    # Sicherstellen, dass der Ordner existiert:
    os.makedirs(os.path.dirname(SET_OVR), exist_ok=True)

    ovr = load_yaml(SET_OVR, {}) or {}
    blk = _ensure(ovr, "settings")
    for k, v in pairs.items():
        if v is not None:
            blk[k] = v
    save_yaml(SET_OVR, ovr)
