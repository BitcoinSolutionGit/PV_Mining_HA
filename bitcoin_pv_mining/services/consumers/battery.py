# services/consumers/battery.py
from __future__ import annotations

import os
from services.consumers.base import BaseConsumer, Desire
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.settings_store import get_var as set_get
from services.ha_entities import call_action

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
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(k) or "").strip()
    return _mget(SENS_OVR, key) or _mget(SENS_DEF, key)

class BatteryConsumer(BaseConsumer):
    id = "battery"
    label = "Battery"

    def compute_desire(self, ctx=None) -> Desire:
        # SoC (0..100)
        soc_ent = _map("battery_soc") or (set_get("battery_soc_sensor", "") or "")
        soc = _num(get_sensor_value(soc_ent) if soc_ent else None, 0.0)

        # Ziel-SoC & max. Ladeleistung
        target_soc = _num(set_get("battery_target_soc", 90.0), 90.0)
        max_kw = _num(
            set_get("battery_max_charge_kw", None)
            or set_get("battery_charge_kw_max", None)
            or (get_sensor_value(_map("battery_charge_power_max_kw")) if _map("battery_charge_power_max_kw") else None),
            0.0
        )

        wants = (soc < target_soc) and (max_kw > 0.0)
        if not wants:
            return Desire(
                wants=False, min_kw=0.0, max_kw=0.0, must_run=False, exact_kw=None,
                reason=f"SoC {soc:.1f}% ≥ target {target_soc:.1f}% or no max power"
            )

        # Batterie ist flexibel → kein must_run, nur PV-Überschuss nutzen
        return Desire(
            wants=True, min_kw=0.0, max_kw=max_kw, must_run=False, exact_kw=None,
            reason=f"charge until {target_soc:.0f}% (SoC {soc:.1f}%)"
        )

    def apply_allocation(self, ctx, alloc_kw: float) -> None:
        """
        Minimal: per Settings definierte Aktionen schalten.
        Optional-Keys:
          - battery_action_on_entity
          - battery_action_off_entity
        """
        on_ent  = set_get("battery_action_on_entity", "") or ""
        off_ent = set_get("battery_action_off_entity", "") or ""

        # >0.05 kW interpretieren wir als "an"
        if alloc_kw > 0.05:
            if on_ent:
                call_action(on_ent, True)
            print(f"[battery] apply ~{alloc_kw:.2f} kW (ON)", flush=True)
        else:
            if off_ent:
                call_action(off_ent, False)
            print("[battery] apply 0 kW (OFF)", flush=True)
