
import os, uuid, time
from services.utils import load_yaml, save_yaml

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

def delete_miner(mid: str):
    miners = [m for m in list_miners() if m.get("id") != mid]
    _save_all({"miners": {"list": miners}})


