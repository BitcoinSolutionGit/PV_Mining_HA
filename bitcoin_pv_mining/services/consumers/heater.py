from __future__ import annotations

import os
import requests
from typing import Optional

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.heater_store import resolve_entity_id, get_var as heat_get

# Helper: read HA token/headers via Supervisor proxy
def _ha_headers():
    tok = os.getenv("SUPERVISOR_TOKEN", "")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"} if tok else {"Content-Type": "application/json"}

def _set_input_number(entity_id: str, value: float) -> bool:
    if not entity_id:
        return False
    try:
        r = requests.post(
            "http://supervisor/core/api/services/input_number/set_value",
            headers=_ha_headers(),
            json={"entity_id": entity_id, "value": float(value)},
            timeout=5
        )
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[HeaterConsumer] set_input_number failed: {e}", flush=True)
        return False

def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

class HeaterConsumer(BaseConsumer):
    id = "heater"; label = "Water Heater"

    def _config(self) -> dict:
        return {
            "warmwasser_id": resolve_entity_id("input_warmwasser_cache") or "",
            "heizstab_id":   resolve_entity_id("input_heizstab_cache") or "",
            "wanted_temp":   _num(heat_get("wanted_water_temperature", 60.0), 60.0),
            "heat_unit":     (heat_get("heat_unit", "°C") or "°C"),
            "max_power":     _num(heat_get("max_power_heater", 0.0), 0.0),
            "power_unit":    (heat_get("power_unit", "kW") or "kW"),
            "manual":        bool(heat_get("manual_override", False)),
        }

    def _target_celsius(self, cfg: dict) -> float:
        tgt = cfg["wanted_temp"]
        if (cfg["heat_unit"] or "°C") == "K":
            return tgt - 273.15
        return tgt

    def _max_power_kw(self, cfg: dict) -> float:
        p = cfg["max_power"]
        unit = cfg["power_unit"] or "kW"
        return p / 1000.0 if unit == "W" else p

    def compute_desire(self, ctx: Ctx | None = None) -> Desire:
        cfg = self._config()
        # Basic checks
        if not cfg["warmwasser_id"] or not cfg["heizstab_id"]:
            return Desire(False, 0.0, 0.0, reason="not configured")
        max_kw = self._max_power_kw(cfg)
        if max_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="max_power=0")

        # Temperatur holen (in °C erwartet)
        from services.ha_sensors import get_sensor_value
        cur_c = _num(get_sensor_value(cfg["warmwasser_id"]), None)
        if cur_c is None:
            return Desire(False, 0.0, 0.0, reason="no temperature")

        target_c = self._target_celsius(cfg)
        # leichte Hysterese von 0.2°C
        if cur_c >= target_c - 0.2:
            return Desire(False, 0.0, 0.0, reason=f"target reached ({cur_c:.2f}°C≥{target_c:.2f}°C)")

        # Im manuellen Modus NICHT automatisch anfordern
        if cfg["manual"]:
            return Desire(False, 0.0, 0.0, reason="manual mode")

        # Wunsch: beliebig bis max_kw (keine Mindestleistung nötig)
        return Desire(True, 0.0, max_kw, must_run=False, reason=f"needs heat ({cur_c:.2f}°C<{target_c:.2f}°C)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        cfg = self._config()
        if not cfg["heizstab_id"]:
            return

        # Wenn manuell, nichts ändern
        if cfg["manual"]:
            return

        max_kw = max(0.0, self._max_power_kw(cfg))
        pct = 0.0
        if max_kw > 1e-6:
            pct = _clamp((alloc_kw / max_kw) * 100.0, 0.0, 100.0)

        # Temperatur-Sicherheitscheck: Bei/über Ziel => 0 %
        from services.ha_sensors import get_sensor_value
        cur_c = _num(get_sensor_value(cfg["warmwasser_id"]), None)
        target_c = self._target_celsius(cfg)
        if cur_c is not None and cur_c >= target_c - 0.0:
            pct = 0.0

        ok = _set_input_number(cfg["heizstab_id"], round(pct, 1))
        if not ok:
            print(f"[HeaterConsumer] failed to apply {pct:.1f}% to {cfg['heizstab_id']}", flush=True)
