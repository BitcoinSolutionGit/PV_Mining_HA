
import os, uuid, time
from services.utils import load_yaml, save_yaml
from services.settings_store import get_var as set_get
from services.ha_entities import call_action, get_entity_state, is_on_like

CONFIG_DIR = "/config/pv_mining_addon"
MIN_DEF = os.path.join(CONFIG_DIR, "miners.yaml")
MIN_OVR = os.path.join(CONFIG_DIR, "miners.local.yaml")

def _ensure(data: dict, path: str) -> dict:
    cur = data
    for k in path.split("."):
        cur = cur.setdefault(k, {})
    return cur

def _get(data: dict, path: str, default=None):
    cur = data
    for k in path.split("."):
        if not isinstance(cur, dict): return default
        cur = cur.get(k)
        if cur is None: return default
    return cur

def _load_all():
    base = load_yaml(MIN_DEF, {}) or {}
    ovr  = load_yaml(MIN_OVR, {}) or {}
    # merge: list kommt komplett aus OVERRIDE, sonst aus DEF
    lst = _get(ovr, "miners.list")
    if not isinstance(lst, list):
        lst = _get(base, "miners.list", [])
    return {"miners": {"list": lst}}


def _list_miners_raw() -> list[dict]:
    return _load_all()["miners"]["list"]

def _save_all(data: dict):
    save_yaml(MIN_OVR, data or {"miners": {"list": []}})

def _state_entity_id(miner: dict) -> str:
    return (
        (miner.get("state_entity") or "")
        or (miner.get("ready_entity") or "")
    ).strip()


def _state_timeout_s(miner: dict, default: int = 10) -> int:
    try:
        raw = miner.get("state_timeout_s")
        if raw is None or str(raw).strip() == "":
            raw = default
        return max(int(float(raw)), default)
    except Exception:
        return default


def _with_runtime(miner: dict) -> dict:
    out = dict(miner or {})
    desired_on = bool(out.get("on"))
    now_ts = time.time()
    pending_on = bool(out.get("pending_on"))
    pending_off = bool(out.get("pending_off"))
    startup_grace_until = _num(out.get("startup_grace_until"), 0.0)
    ha_on = None
    try:
        state_entity = _state_entity_id(out)
        if state_entity:
            state = get_entity_state(state_entity)
            if state is not None:
                ha_on = is_on_like(state)
    except Exception:
        ha_on = None

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

    if ha_on is True:
        effective_on = True
        phase = "running"
    elif pending_on:
        effective_on = True
        phase = "starting" if (startup_grace_until <= 0.0 or now_ts < startup_grace_until) else "start_failed"
    elif pending_off:
        effective_on = True
        phase = "stopping"
    elif ha_on is False:
        effective_on = False
        phase = "off"
    elif desired_on:
        effective_on = True
        phase = "running_no_state"
    else:
        effective_on = False
        phase = "off"

    out["desired_on"] = desired_on
    out["ha_on"] = ha_on
    out["pending_on"] = pending_on
    out["pending_off"] = pending_off
    out["startup_grace_until"] = startup_grace_until
    out["effective_on"] = effective_on
    out["phase"] = phase
    return out


def list_miners() -> list[dict]:
    return [_with_runtime(m) for m in _list_miners_raw()]


def get_miner(mid: str) -> dict | None:
    for miner in list_miners():
        if miner.get("id") == mid:
            return miner
    return None

def _new_id() -> str:
    return "m_" + uuid.uuid4().hex[:10]

def add_miner(name: str = "") -> dict:
    miners = _list_miners_raw()
    item = {
        "id": _new_id(),
        "name": name or f"Miner {len(miners)+1}",
        "enabled": True,
        "mode": "manual",     # "manual" | "auto"
        "on": False,          # gewünschter Zustand (manual) / angezeigter Zustand (auto)
        "state_entity": "",
        "state_timeout_s": 10,
        "pending_on": False,
        "pending_off": False,
        "startup_grace_until": 0.0,
        "hashrate_ths": 100.0,
        "power_kw": 3.0,
        "require_cooling": False,
        "action_on_entity": "",
        "action_off_entity": "",
        "created_at": int(time.time()),
    }
    miners.append(item)
    _save_all({"miners": {"list": miners}})
    return item

def update_miner(mid: str, **changes):
    miners = _list_miners_raw()
    for m in miners:
        if m.get("id") == mid:
            m.update({k: v for k, v in changes.items() if v is not None})
            break
    _save_all({"miners": {"list": miners}})


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def miner_runtime_lock(mid: str, target_on: bool, now_ts: float | None = None) -> tuple[bool, str]:
    miner = get_miner(mid)
    if not miner:
        return True, "not found"

    now_eff = float(now_ts if now_ts is not None else time.time())
    actual_on = bool(miner.get("effective_on")) if miner.get("ha_on") is not None else bool(miner.get("on"))
    last_flip_ts = _num(miner.get("last_flip_ts"), 0.0)
    elapsed = max(0.0, now_eff - last_flip_ts) if last_flip_ts > 0.0 else 10**9

    if target_on:
        min_off_s = int(_num(set_get("miner_min_off_s", 20), 20))
        if (not actual_on) and last_flip_ts > 0.0 and elapsed < max(0, min_off_s):
            return True, f"min-off lock {max(0, int(min_off_s - elapsed))}s"
    else:
        per_miner_run = set_get(f"miner.{mid}.min_run_min", None)
        if per_miner_run is not None:
            try:
                min_run_s = max(0, int(float(per_miner_run) * 60.0))
            except Exception:
                min_run_s = int(_num(set_get("miner_min_run_s", 30), 30))
        else:
            min_run_s = int(_num(set_get("miner_min_run_s", 30), 30))
        if actual_on and last_flip_ts > 0.0 and elapsed < max(0, min_run_s):
            return True, f"min-run lock {max(0, int(min_run_s - elapsed))}s"

    return False, ""


def request_miner_state(mid: str, target_on: bool, *, now_ts: float | None = None, enforce_runtime: bool = True) -> tuple[bool, str]:
    miner = get_miner(mid)
    if not miner:
        return False, "not found"

    current_on = bool(miner.get("on"))
    if current_on == bool(target_on):
        return True, "unchanged"

    now_eff = float(now_ts if now_ts is not None else time.time())
    if enforce_runtime:
        locked, reason = miner_runtime_lock(mid, bool(target_on), now_eff)
        if locked:
            return False, reason

    action_key = "action_on_entity" if target_on else "action_off_entity"
    action_entity = (miner.get(action_key) or "").strip()
    if action_entity:
        call_action(action_entity, bool(target_on))

    has_feedback = bool(_state_entity_id(miner))
    timeout_s = _state_timeout_s(miner, 10)
    update_miner(
        mid,
        on=bool(target_on),
        pending_on=(bool(target_on) and has_feedback),
        pending_off=((not bool(target_on)) and has_feedback and bool(miner.get("effective_on", miner.get("on")))),
        startup_grace_until=(now_eff + timeout_s) if has_feedback else 0.0,
        last_flip_ts=now_eff,
    )
    return True, "switched"

def delete_miner(mid: str):
    miners = [m for m in _list_miners_raw() if m.get("id") != mid]
    _save_all({"miners": {"list": miners}})


