# services/cooling_store.py
import os, time
from services.utils import load_yaml, save_yaml
from services.ha_entities import get_entity_state, is_on_like

CONFIG_DIR = "/config/pv_mining_addon"
COOL_DEF = os.path.join(CONFIG_DIR, "cooling.yaml")
COOL_OVR  = os.path.join(CONFIG_DIR, "cooling.local.yaml")

_DEFAULT = {
    "id": "cooling",
    "name": "Cooling circuit",
    "enabled": True,
    "mode": "manual",  # "manual" | "auto"
    "on": False,
    "pending_on": False,
    "pending_off": False,
    "startup_grace_until": 0.0,
    "last_transition_ts": 0.0,
    "power_kw": 0.5,
    "action_on_entity": "",
    "action_off_entity": "",
    "state_entity": "",
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

def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def get_cooling() -> dict:
    base = load_yaml(COOL_DEF, {}) or {}
    ovr  = load_yaml(COOL_OVR, {}) or {}
    data = _merge(base.get("cooling", {}), ovr.get("cooling", {}))
    out = _merge(_DEFAULT, data)

    # Wunschzustand AUS DER UI merken (nicht überschreiben!)
    desired_on = bool(out.get("on"))

    # Tatsächlichen Zustand aus HA lesen (kann True/False/None sein)
    ha_on = None
    try:
        rid = ((out.get("state_entity") or "") or (out.get("ready_entity") or "")).strip()
        if rid:
            state = get_entity_state(rid)  # "on" / "off" / "unavailable" / ...
            ha_on = is_on_like(state)  # robustes Mapping
    except Exception:
        ha_on = None

    now_ts = time.time()
    pending_on = _truthy(out.get("pending_on"))
    pending_off = _truthy(out.get("pending_off"))
    startup_grace_until = _num(out.get("startup_grace_until"), 0.0)

    if ha_on is True:
        pending_on = False
        pending_off = False
        startup_grace_until = 0.0
    elif ha_on is False:
        if pending_off:
            pending_off = False
        if pending_on and startup_grace_until > 0.0 and now_ts >= startup_grace_until:
            pending_on = False
            startup_grace_until = 0.0

    effective_on = False
    phase = "off"
    if ha_on is True:
        effective_on = True
        phase = "running"
    elif pending_on:
        effective_on = True
        phase = "starting" if (startup_grace_until <= 0.0 or now_ts < startup_grace_until) else "start_failed"
    elif pending_off:
        phase = "stopping"
    elif ha_on is None and desired_on:
        effective_on = True
        phase = "running_no_ready"

    out["on"] = desired_on
    out["ha_on"] = ha_on
    out["pending_on"] = pending_on
    out["pending_off"] = pending_off
    out["startup_grace_until"] = startup_grace_until
    out["effective_on"] = effective_on
    out["phase"] = phase
    return out



def set_cooling(**changes):
    cur = get_cooling()
    cur.update({k: v for k, v in (changes or {}).items() if v is not None})
    # dynamische Felder nicht persistieren
    cur.pop("ha_on", None)
    cur.pop("effective_on", None)
    cur.pop("phase", None)
    save_yaml(COOL_OVR, {"cooling": cur})
