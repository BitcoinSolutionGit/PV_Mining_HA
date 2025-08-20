# services/consumers/heater_consumer.py
from __future__ import annotations
import os, time, requests
from typing import Optional

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.ha_sensors import get_sensor_value
from services.heater_store import resolve_entity_id as heat_resolve, get_var as heat_get

# kleiner Speicher für Kick-Cooldown
_last_kick_ts: float = 0.0

def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

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
            timeout=5,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False

class HeaterConsumer(BaseConsumer):
    """
    Steuert den Wasser-Heizstab über den Cache-Input (0–100 %) im Auto-Modus.
    Optionaler 'Kickstart' hilft Zero-Feed-In-Invertern anzulaufen.
    """
    id: str = "heater"

    def _read_cfg(self):
        enabled = bool(heat_get("enabled", False))
        auto    = not bool(heat_get("manual_override", False))  # override=True => manuell
        max_kw  = _num(heat_get("max_power_heater", 0.0), 0.0)

        t_target = _num(heat_get("wanted_water_temperature", 0.0), 0.0)
        t_sens   = (heat_resolve("sensor_water_temperature") or "").strip()
        pct_inp  = (heat_resolve("input_heizstab_cache") or "").strip()
        return enabled, auto, max_kw, t_target, t_sens, pct_inp

    def compute_desire(self, ctx: Ctx) -> Desire:
        enabled, auto, max_kw, t_target, t_sens, pct_inp = self._read_cfg()
        if not enabled:
            return Desire(False, 0.0, 0.0, None, False, "disabled")
        if not auto:
            return Desire(False, 0.0, 0.0, None, False, "manual mode")
        if max_kw <= 0.0 or not t_sens or not pct_inp:
            return Desire(False, 0.0, 0.0, None, False, "not configured")

        # Temperatur prüfen
        try:
            t_now = _num(get_sensor_value(t_sens), None)
        except Exception:
            t_now = None
        if t_now is None:
            return Desire(False, 0.0, 0.0, None, False, "no water temp")

        # einfache Hysterese
        if t_now >= (t_target - 0.5):
            return Desire(False, 0.0, 0.0, None, False, "target reached")

        # Grund-Desire: bis zur Max-Leistung erlauben
        wants   = True
        min_kw  = 0.0
        max_kw  = max(0.0, max_kw)
        must    = False
        reason  = "heat towards target"

        # --- Zero-Export-Kick: kleiner Pflicht-Minimalwert, um Inverter anlaufen zu lassen ---
        kick_on   = bool(heat_get("zero_export_kick_enabled", False))
        kick_kw   = _num(heat_get("zero_export_kick_kw", 0.2), 0.2)  # 200 W
        cooldown  = _num(heat_get("zero_export_kick_cooldown_s", 60), 60)

        if kick_on and kick_kw > 0.0:
            # Falls wir praktisch "stehen": aktueller Prozentwert sehr klein?
            try:
                pct_now = _num(get_sensor_value(pct_inp), 0.0)
            except Exception:
                pct_now = 0.0

            global _last_kick_ts
            enough_cooldown = (time.time() - _last_kick_ts) > cooldown
            if pct_now < 5.0 and enough_cooldown:
                # kleinen Pflichtanteil einfordern (Planner darf dafür kurz Grid ziehen)
                min_kw = min(kick_kw, max_kw)
                must   = True
                reason += " | kickstart"

        return Desire(wants, min_kw, max_kw, None, must, reason)

    def apply_allocation(self, ctx: Ctx, kw: float) -> None:
        """
        Allocation in Prozent auf den Cache-Input schreiben.
        """
        enabled, auto, max_kw, _t_target, _t_sens, pct_inp = self._read_cfg()
        if not enabled or not auto or max_kw <= 0.0 or not pct_inp:
            return
        pct = max(0.0, min(100.0, (kw / max_kw) * 100.0))
        ok = _set_input_number(pct_inp, round(pct))
        if ok and pct >= 5.0:
            # Kick erfolgreich -> Cooldown starten
            global _last_kick_ts
            _last_kick_ts = time.time()
