# services/consumers/house.py
from __future__ import annotations

import os
from services.consumers.base import Desire
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")

def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d

def _map(key: str) -> str:
    def _mget(path, k):
        try:
            m = (load_yaml(path, {}).get("mapping", {}) or {})
            return (m.get(k) or "").strip()
        except Exception:
            return ""
    return _mget(SENS_OVR, key) or _mget(SENS_DEF, key)

class HouseLoadConsumer:
    """Undrosselbarer Grundlast-Verbraucher (Hauslast)."""
    id = "house"
    label = "House load"
    is_dispatchable = False  # nicht steuer-/abschaltbar

    def compute_desire(self, ctx=None) -> Desire:
        # Versuche mehrere mögliche Mapping-Keys
        sens = _map("house_load") or _map("house_consumption") or _map("load")
        val_kw = _num(get_sensor_value(sens) if sens else 0.0, 0.0)

        # Falls der Sensor in W statt kW liefert, einfache Heuristik:
        if val_kw > 100.0:  # >100 kW ist unplausibel -> vermutlich W
            val_kw = val_kw / 1000.0

        return Desire(
            wants=True,
            min_kw=0.0,
            max_kw=val_kw,
            exact_kw=val_kw,      # Hauslast muss bedient werden
            must_run=True,
            reason=("measured house load" if sens else "no house sensor configured"),
        )
