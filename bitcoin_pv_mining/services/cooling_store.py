# services/cooling_store.py
import os, time
from services.utils import load_yaml, save_yaml
from services.ha_sensors import get_sensor_value

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
    "action_on_entity": "",
    "action_off_entity": "",
    "ready_entity": "",
    "created_at": int(time.time()),
}

def _merge(base: dict, ovr: dict) -> dict:
    d = (base or {}).copy()
    d.update(ovr or {})
    return d

def _truthy(x) -> bool:
    s = str(x).strip().lower()
    if s in ("1","true","on","yes","y","enabled"):
        return True
    try:
        return float(s) > 0.0
    except Exception:
        return False

def get_cooling() -> dict:
    base = load_yaml(COOL_DEF, {}) or {}
    ovr  = load_yaml(COOL_OVR, {}) or {}
    data = _merge(base.get("cooling", {}), ovr.get("cooling", {}))
    out = _merge(_DEFAULT, data)
    # Wenn ready_entity gesetzt ist, hat deren HA-Wert Vorrang für "on"
    try:
        rid = (out.get("ready_entity") or "").strip()
        if rid:
            val = get_sensor_value(rid)
            out["on"] = _truthy(val)
    except Exception:
        pass
    return out

def set_cooling(**changes):
    cur = get_cooling()
    cur.update({k: v for k, v in (changes or {}).items() if v is not None})
    save_yaml(COOL_OVR, {"cooling": cur})
