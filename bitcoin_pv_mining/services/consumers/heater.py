# services/consumers/heater_consumer.py
from __future__ import annotations
import os, time, requests
from typing import Optional

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.ha_sensors import get_sensor_value
from services.heater_store import resolve_entity_id as heat_resolve, get_var as heat_get

# simple cooldown memory for kick
_last_kick_ts: float = 0.0

def _num(x, d=None):
    try:
        if x in (None, ""):
            return d
        return float(x)
    except Exception:
        return d

def _log(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass

def _ha_headers():
    tok = os.getenv("SUPERVISOR_TOKEN", "")
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

def _set_percent_entity(entity_id: str, value: float) -> bool:
    """Supports input_number.* and number.*"""
    if not entity_id:
        return False
    try:
        if entity_id.startswith("input_number."):
            url = "http://supervisor/core/api/services/input_number/set_value"
        elif entity_id.startswith("number."):
            url = "http://supervisor/core/api/services/number/set_value"
        else:
            _log(f"[heater] unsupported target entity: {entity_id}")
            return False
        r = requests.post(url, headers=_ha_headers(),
                          json={"entity_id": entity_id, "value": float(value)},
                          timeout=5)
        ok = r.status_code in (200, 201)
        if not ok:
            _log(f"[heater] set_value HTTP {r.status_code} for {entity_id}={value}")
        return ok
    except Exception as e:
        _log(f"[heater] set_value failed for {entity_id}: {e}")
        return False

class HeaterConsumer(BaseConsumer):
    """Follows PV surplus by writing % to a cache entity in Auto mode."""
    # be compatible with any registry that looks for either name
    id  = "heater"
    cid = "heater"

    def _read_cfg(self):
        enabled = bool(heat_get("enabled", False))
        auto    = not bool(heat_get("manual_override", False))  # override=True => manual
        max_kw  = _num(heat_get("max_power_heater", 0.0), 0.0)

        t_target = _num(heat_get("wanted_water_temperature", 0.0), 0.0)
        # prefer real water sensor, fallback to warmwasser_cache if needed
        t_sens   = (heat_resolve("sensor_water_temperature")
                    or heat_resolve("input_warmwasser_cache")
                    or "").strip()
        pct_tgt  = (heat_resolve("input_heizstab_cache")
                    or heat_resolve("slider_water_heater_percent")
                    or "").strip()
        return enabled, auto, max_kw, t_target, t_sens, pct_tgt

    def compute_desire(self, ctx: Ctx) -> Desire:
        enabled, auto, max_kw, t_target, t_sens, pct_tgt = self._read_cfg()
        if not enabled:
            return Desire(False, 0.0, 0.0, None, False, "disabled")
        if not auto:
            return Desire(False, 0.0, 0.0, None, False, "manual mode")
        if max_kw is None or max_kw <= 0.0 or not pct_tgt:
            return Desire(False, 0.0, 0.0, None, False, "not configured")

        t_now = _num(get_sensor_value(t_sens), None) if t_sens else None
        if t_now is None:
            return Desire(False, 0.0, 0.0, None, False, "no water temp")

        # small hysteresis near target
        if t_now >= (t_target - 0.5):
            return Desire(False, 0.0, 0.0, None, False, "target reached")

        wants   = True
        min_kw  = 0.0
        max_kw  = max(0.0, max_kw)
        must    = False
        reason  = f"heat towards target (T={t_now:.1f}<{t_target:.1f})"

        # --- Zero-export kick (optional) ---
        kick_on  = bool(heat_get("zero_export_kick_enabled", False))
        kick_kw  = _num(heat_get("zero_export_kick_kw", 0.2), 0.2)  # kW
        cooldown = _num(heat_get("zero_export_kick_cooldown_s", 60), 60)

        if kick_on and kick_kw and kick_kw > 0.0:
            # don't gate the kick only by cached %, that can be stale after manual mode
            try:
                pct_now = _num(get_sensor_value(pct_tgt), 0.0)
            except Exception:
                pct_now = 0.0
            enough_cooldown = (time.time() - _last_kick_ts) > float(cooldown or 0)

            # Kick if our command is effectively low OR we just switched to auto
            if (pct_now is None or pct_now < 5.0) and enough_cooldown:
                min_kw = min(kick_kw, max_kw)
                must   = True
                reason += " | kickstart"

        return Desire(wants, min_kw, max_kw, None, must, reason)

    def apply_allocation(self, ctx: Ctx, kw: float) -> None:
        enabled, auto, max_kw, _t_target, _t_sens, pct_tgt = self._read_cfg()
        if not enabled or not auto or not pct_tgt or not max_kw or max_kw <= 0.0:
            _log(f"[heater] skip apply (enabled={enabled} auto={auto} tgt='{pct_tgt}' max_kw={max_kw})")
            return

        pct = max(0.0, min(100.0, (float(kw) / float(max_kw)) * 100.0))
        ok = _set_percent_entity(pct_tgt, round(pct))
        _log(f"[heater] apply kw={kw:.3f} -> {pct:.1f}% target={pct_tgt} ok={ok}")

        # start cooldown once we actually commanded >= ~5%
        if ok and pct >= 5.0:
            global _last_kick_ts
            _last_kick_ts = time.time()
