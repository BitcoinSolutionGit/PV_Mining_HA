# services/orchestrator.py
from __future__ import annotations
from typing import List, Dict, Any
import os
from services.utils import load_yaml
from services.settings_store import get_var as set_get
from services.cooling_store import get_cooling
from services.ha_sensors import get_sensor_value
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.consumers.base import Ctx, now
from services.consumers.registry import get_consumer_for_id

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")

def _map_id(kind: str) -> str:
    def _mget(path, key):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(key) or "").strip()
    return _mget(SENS_OVR, kind) or _mget(SENS_DEF, kind)

def _load_prio_ids() -> List[str]:
    raw = set_get("priority_order", None)
    if isinstance(raw, list) and raw:
        return raw
    import json
    raw_json = set_get("priority_order_json", "")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            val = json.loads(raw_json)
            if isinstance(val, list) and val:
                return val
        except Exception:
            pass
    return []

def _ctx_now() -> Ctx:
    pv_id   = _map_id("pv_production")
    grid_id = _map_id("grid_consumption")
    feed_id = _map_id("grid_feed_in")
    return {
        "price": elec_price() or 0.0,
        "fee_down": float(elec_get("network_fee_down_value", 0.0) or 0.0),
        "pv_kw": float(get_sensor_value(pv_id) or 0.0) if pv_id else 0.0,
        "grid_kw": float(get_sensor_value(grid_id) or 0.0) if grid_id else 0.0,
        "feed_in_kw": max(float(get_sensor_value(feed_id) or 0.0), 0.0) if feed_id else 0.0,
        "now": now(),
        "cooling": get_cooling() or {},
    }

def dry_run_plan() -> List[Dict[str, Any]]:
    plan = []
    order = _load_prio_ids()
    ctx = _ctx_now()
    for cid in order:
        cons = get_consumer_for_id(cid)
        if not cons:
            continue
        d = cons.compute_desire(ctx)
        plan.append({"id": cid, "desire": d})
    return plan

def log_dry_run_plan(prefix: str = "[plan]"):
    try:
        plan = dry_run_plan()
        for row in plan:
            d = row["desire"]
            print(f"{prefix} {row['id']}: wants={d.wants} "
                  f"min={d.min_kw:.3f} max={d.max_kw:.3f} "
                  f"exact={d.exact_kw} must_run={d.must_run} reason={d.reason}", flush=True)
    except Exception as e:
        print(f"{prefix} error: {e}", flush=True)
