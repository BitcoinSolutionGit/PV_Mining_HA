# services/consumers/battery.py
from __future__ import annotations
import os

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.battery_store import get_var as bat_get   # <— HIER lesen wir jetzt
from services.settings_store import get_var as set_get   # (nur noch für Policies, falls nötig)

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

def _read_power_kw(self) -> float | None:
    p_ent = bat_get("power_entity", "")
    if p_ent:
        return _num(get_sensor_value(p_ent), None)  # schon kW

    # Fallback: DC-Spannung * DC-Strom (in kW), Stromvorzeichen bestimmt +/- (laden/entladen)
    v_ent = bat_get("voltage_entity", "")
    i_ent = bat_get("current_entity", "")
    try:
        v = _num(get_sensor_value(v_ent), None)
        i = _num(get_sensor_value(i_ent), None)
        if v is None or i is None:
            return None
        return (v * i) / 1000.0  # kW
    except Exception:
        return None

class BatteryConsumer(BaseConsumer):
    id = "battery"
    label = "Battery"

    # ---- kleine Reader-Helpers ----
    def _read_soc(self) -> float:
        ent = bat_get("soc_entity", "") or ""
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _read_voltage(self) -> float:
        ent = bat_get("dc_voltage_entity", "") or ""
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _read_current(self) -> float:
        ent = bat_get("dc_current_entity", "") or ""
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _measured_power_kw(self) -> float | None:
        """+kW = Laden, -kW = Entladen. Liefert None, wenn U/I fehlen."""
        v = self._read_voltage()
        a = self._read_current()
        if abs(v) <= 1e-6 or abs(a) <= 1e-6:
            # Optionaler Legacy-Sensor:
            p_ent = bat_get("power_entity", "") or ""
            if p_ent:
                return _num(get_sensor_value(p_ent), 0.0)
            return None
        return (v * a) / 1000.0

    def _target_soc(self) -> float:
        return _num(bat_get("target_soc", 90.0), 90.0)

    def _max_charge_kw(self) -> float:
        return _num(bat_get("max_charge_kw", 0.0), 0.0)

    # ---- Scheduling-Logik ----
    def compute_desire(self, ctx: Ctx) -> Desire:
        soc     = self._read_soc()
        target  = self._target_soc()
        max_kw  = max(0.0, self._max_charge_kw())
        surplus = max(0.0, ctx.surplus_kw)

        if max_kw <= 0:
            return Desire(False, 0.0, 0.0, reason="no max power configured")
        if soc >= target:
            return Desire(False, 0.0, 0.0, reason=f"SoC {soc:.1f}% ≥ target {target:.1f}%")
        if surplus <= 0:
            return Desire(False, 0.0, 0.0, reason="no PV surplus")

        want = min(max_kw, surplus)
        return Desire(True, 0.0, want, reason=f"charge up to {want:.3f} kW (SoC {soc:.1f}% < {target:.1f}%)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Keine direkte Aktorik: die Batterie folgt der Physik (Laden bei PV-Überschuss).
        Wir loggen nur.
        """
        print(f"[battery] alloc request ~{alloc_kw:.2f} kW (no external control)", flush=True)


