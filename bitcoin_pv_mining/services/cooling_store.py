import os, time
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
COOL_DEF = os.path.join(CONFIG_DIR, "cooling.yaml")
COOL_OVR  = os.path.join(CONFIG_DIR, "cooling.local.yaml")

_DEFAULT = {
    "id": "cooling",
    "name": "Cooling circuit",
    "enabled": True,
    "mode": "manual",  # "manual" | "auto"
    "on": False,
    "power_kw": 0.5,
    "created_at": int(time.time()),
}

def _merge(base: dict, ovr: dict) -> dict:
    d = (base or {}).copy()
    d.update(ovr or {})
    return d

def get_cooling() -> dict:
    base = load_yaml(COOL_DEF, {}) or {}
    ovr  = load_yaml(COOL_OVR, {}) or {}
    data = _merge(base.get("cooling", {}), ovr.get("cooling", {}))
    return _merge(_DEFAULT, data)

def set_cooling(**changes):
    cur = get_cooling()
    cur.update({k: v for k, v in (changes or {}).items() if v is not None})
    save_yaml(COOL_OVR, {"cooling": cur})
