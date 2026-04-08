
import os, uuid, time
from services.utils import load_yaml, save_yaml
from services.settings_store import get_var as set_get
from services.ha_entities import call_action

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

def _save_all(data: dict):
    save_yaml(MIN_OVR, data or {"miners": {"list": []}})

def list_miners() -> list[dict]:
    return _load_all()["miners"]["list"]


def get_miner(mid: str) -> dict | None:
    for miner in list_miners():
        if miner.get("id") == mid:
            return miner
    return None

def _new_id() -> str:
    return "m_" + uuid.uuid4().hex[:10]

def add_miner(name: str = "") -> dict:
    miners = list_miners()
    item = {
        "id": _new_id(),
        "name": name or f"Miner {len(miners)+1}",
        "enabled": True,
        "mode": "manual",     # "manual" | "auto"
        "on": False,          # gewünschter Zustand (manual) / angezeigter Zustand (auto)
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
    miners = list_miners()
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
    actual_on = bool(miner.get("on"))
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

    update_miner(mid, on=bool(target_on), last_flip_ts=now_eff)
    return True, "switched"

def delete_miner(mid: str):
    miners = [m for m in list_miners() if m.get("id") != mid]
    _save_all({"miners": {"list": miners}})


