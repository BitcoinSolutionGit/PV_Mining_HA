# services/consumers/battery.py
from __future__ import annotations
from .base import Consumer, Desire, Ctx
from services.settings_store import get_var as set_get
from services.ha_sensors import get_sensor_value
from services.utils import load_yaml
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

class BatteryConsumer(Consumer):
    id = "battery"
    label = "Battery (charge)"

    def _soc(self) -> float:
        sens = _map_id("battery_soc")
        if sens:
            return max(min(_num(get_sensor_value(sens), 0.0), 100.0), 0.0)
        # Fallback: Settings-Wert, falls jemand Sensor → Helper mapped
        return max(min(_num(set_get("battery_soc_percent", 0.0), 0.0), 100.0), 0.0)

    def _cfg(self):
        # minimale Konfig – kann später in UI editiert werden
        return {
            "min_soc":     _num(set_get("battery_min_soc", 20.0), 20.0),
            "max_soc":     _num(set_get("battery_max_soc", 95.0), 95.0),
            "reserve_soc": _num(set_get("battery_reserve_soc", 10.0), 10.0),
            "p_charge_kw": _num(set_get("battery_charge_kw_max", 3.0), 3.0),
            # p_discharge_kw folgt in „Discharge“-Schritt
        }

    def compute_desire(self, ctx: Ctx) -> Desire:
        soc = self._soc()
        cfg = self._cfg()

        # nur Auto-Laden aus PV-Überschuss (feed_in_kw)
        feed = max(_num(ctx.get("feed_in_kw"), 0.0), 0.0)

        # Wenn SOC >= max → kein Ladewunsch
        if soc >= cfg["max_soc"] - 1e-6:
            return Desire(False, 0.0, 0.0, reason=f"SOC {soc:.1f}% ≥ max {cfg['max_soc']}%")

        # Wenn kein Überschuss → kein Ladewunsch (vorerst; Grid-Laden später optional)
        if feed <= 0.01:
            return Desire(False, 0.0, 0.0, reason="no PV surplus")

        # Ladeleistung begrenzen auf (max Charge, Überschuss)
        max_kw = max(min(cfg["p_charge_kw"], feed), 0.0)
        if max_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no allocatable surplus")

        # Battery ist „weich“: sie *will* bis max_kw, muss aber nicht (kein must_run)
        return Desire(True, 0.0, max_kw, must_run=False, exact_kw=None,
                      reason=f"charge towards {cfg['max_soc']}% (SOC {soc:.1f}%)")

    def apply(self, allocated_kw: float, ctx: Ctx) -> None:
        # Steuerung folgt in einem späteren Schritt (Services → Charger/Switch)
        return
