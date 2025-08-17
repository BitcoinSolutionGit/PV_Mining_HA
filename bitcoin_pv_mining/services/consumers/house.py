# services/consumers/house.py
from __future__ import annotations
from typing import Dict, Any
from .base import Consumer, Desire, Ctx
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
import os

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")

def _map_id(kind: str) -> str:
    def _mget(path, key):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(key) or "").strip()
    return _mget(SENS_OVR, kind) or _mget(SENS_DEF, kind)

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

class HouseLoadConsumer(Consumer):
    id = "house"
    label = "House load"

    def _house_kw_now(self, ctx: Ctx) -> float:
        # 1) Bevorzugt expliziter Sensor
        sens = _map_id("house_consumption")
        if sens:
            v = _num(get_sensor_value(sens), 0.0)
            if v >= 0: return v
        # 2) Fallback Schätzung: (PV + Grid) – Feed-in
        pv    = _num(ctx.get("pv_kw"), 0.0)
        grid  = _num(ctx.get("grid_kw"), 0.0)
        feed  = max(_num(ctx.get("feed_in_kw"), 0.0), 0.0)
        return max(pv + grid - feed, 0.0)

    def compute_desire(self, ctx: Ctx) -> Desire:
        kw = self._house_kw_now(ctx)
        # House ist nicht abschaltbar → exact, must_run
        return Desire(True, kw, kw, must_run=True, exact_kw=kw, reason="measured house load")

    def apply(self, allocated_kw: float, ctx: Ctx) -> None:
        # House wird nicht aktiv geschaltet
        return
