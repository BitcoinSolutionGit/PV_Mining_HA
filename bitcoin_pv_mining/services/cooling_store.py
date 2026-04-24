# services/cooling_store.py
import os, time
from services.utils import load_yaml, save_yaml
from services.ha_entities import get_entity_state, is_on_like

CONFIG_DIR = "/config/pv_mining_addon"
COOL_DEF = os.path.join(CONFIG_DIR, "cooling.yaml")
COOL_OVR = os.path.join(CONFIG_DIR, "cooling.local.yaml")

_DEFAULT = {
    "id": "cooling",
    "name": "Cooling circuit",
    "enabled": True,
    "mode": "manual",  # "manual" | "auto"
    "on": False,
    "pending_on": False,
    "pending_off": False,
    "confirm_deadline_ts": 0.0,
    "fail_deadline_ts": 0.0,
    "failed_phase": "",
    "last_transition_ts": 0.0,
    "power_kw": 0.5,
    "action_on_entity": "",
    "action_off_entity": "",
    "state_entity": "",
    "state_timeout_s": 60,
    "created_at": int(time.time()),
}


def _merge(base: dict, ovr: dict) -> dict:
    d = (base or {}).copy()
    d.update(ovr or {})
    return d


def _truthy(x) -> bool:
    s = str(x).strip().lower()
    if s in ("1", "true", "on", "yes", "y", "enabled"):
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


def _state_timeout_s(c: dict | None = None, default: int = 60) -> int:
    try:
        raw = (c or {}).get("state_timeout_s")
        if raw is None or str(raw).strip() == "":
            raw = (c or {}).get("ready_timeout_s")
        if raw is None or str(raw).strip() == "":
            raw = default
        return max(int(float(raw)), 1)
    except Exception:
        return default


def get_cooling() -> dict:
    base = load_yaml(COOL_DEF, {}) or {}
    ovr = load_yaml(COOL_OVR, {}) or {}
    data = _merge(base.get("cooling", {}), ovr.get("cooling", {}))
    out = _merge(_DEFAULT, data)
    out["state_timeout_s"] = _state_timeout_s(out, _DEFAULT["state_timeout_s"])

    desired_on = bool(out.get("on"))
    state_entity = (out.get("state_entity") or "").strip()

    ha_on = None
    try:
        if state_entity:
            state = get_entity_state(state_entity)
            ha_on = is_on_like(state)
    except Exception:
        ha_on = None

    now_ts = time.time()
    pending_on = _truthy(out.get("pending_on"))
    pending_off = _truthy(out.get("pending_off"))
    confirm_deadline_ts = _num(out.get("confirm_deadline_ts", out.get("startup_grace_until")), 0.0)
    fail_deadline_ts = _num(out.get("fail_deadline_ts"), 0.0)
    failed_phase = str(out.get("failed_phase") or "").strip().lower()

    if pending_on:
        if ha_on is True:
            pending_on = False
            confirm_deadline_ts = 0.0
            fail_deadline_ts = 0.0
            failed_phase = ""
        elif fail_deadline_ts > 0.0 and now_ts >= fail_deadline_ts:
            pending_on = False
            confirm_deadline_ts = 0.0
            fail_deadline_ts = 0.0
            failed_phase = "start_failed"

    if pending_off:
        if ha_on is False:
            pending_off = False
            confirm_deadline_ts = 0.0
            fail_deadline_ts = 0.0
            failed_phase = ""
        elif fail_deadline_ts > 0.0 and now_ts >= fail_deadline_ts:
            pending_off = False
            confirm_deadline_ts = 0.0
            fail_deadline_ts = 0.0
            failed_phase = "stop_failed"

    if ha_on is True and desired_on:
        failed_phase = ""
    elif ha_on is False and not desired_on:
        failed_phase = ""

    effective_on = False
    phase = "off"
    if pending_on:
        effective_on = True
        phase = "starting"
    elif pending_off:
        effective_on = True
        phase = "stopping"
    elif failed_phase == "start_failed" and desired_on:
        phase = "start_failed"
    elif failed_phase == "stop_failed" and not desired_on:
        effective_on = (ha_on is True)
        phase = "stop_failed"
    elif ha_on is True:
        effective_on = True
        phase = "running"
    elif ha_on is None and desired_on:
        effective_on = True
        phase = "running_no_state"

    out["on"] = desired_on
    out["ha_on"] = ha_on
    out["pending_on"] = pending_on
    out["pending_off"] = pending_off
    out["confirm_deadline_ts"] = confirm_deadline_ts
    out["fail_deadline_ts"] = fail_deadline_ts
    out["startup_grace_until"] = confirm_deadline_ts
    out["failed_phase"] = failed_phase
    out["effective_on"] = effective_on
    out["phase"] = phase
    return out


def set_cooling(**changes):
    cur = get_cooling()
    changes = dict(changes or {})
    if "startup_grace_until" in changes and "confirm_deadline_ts" not in changes:
        changes["confirm_deadline_ts"] = changes.get("startup_grace_until")
    if "ready_timeout_s" in changes and "state_timeout_s" not in changes:
        changes["state_timeout_s"] = changes.get("ready_timeout_s")
    cur.update({k: v for k, v in changes.items() if v is not None})
    cur["state_timeout_s"] = _state_timeout_s(cur, _DEFAULT["state_timeout_s"])
    cur.pop("ready_entity", None)
    cur.pop("ready_timeout_s", None)
    cur.pop("ha_on", None)
    cur.pop("effective_on", None)
    cur.pop("phase", None)
    save_yaml(COOL_OVR, {"cooling": cur})
