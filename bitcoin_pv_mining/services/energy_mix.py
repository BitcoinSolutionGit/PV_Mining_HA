# services/energy_mix.py
from __future__ import annotations
from typing import Optional, Tuple
import os

from services.ha_sensors import get_sensor_value
from services.settings_store import get_var as set_get
from services.battery_store import get_var as bat_get
from services.sensor_mapping import resolve_sensor_id as resolve_runtime_sensor_id
try:
    from services.dev_mock import (
        effective_entity_key,
        DEV_BATTERY_VOLTAGE,
        DEV_BATTERY_CURRENT,
        DEV_HEATER_PERCENT,
    )
except Exception:
    DEV_BATTERY_VOLTAGE = "mock:battery_voltage"
    DEV_BATTERY_CURRENT = "mock:battery_current"
    DEV_HEATER_PERCENT = "mock:heater_percent"

    def effective_entity_key(entity_id, _mock_key):
        return (entity_id or "").strip()

def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d

def _kw(val: float) -> float:
    """Heuristik: falls der Sensor in W liefert, nach kW umrechnen."""
    try:
        v = float(val)
    except Exception:
        return 0.0
    return v / 1000.0 if abs(v) > 2000 else v

def _map(key: str) -> str:
    return resolve_runtime_sensor_id(key, allow_mock=True)

def _read_opt_kw(map_key: str) -> Optional[float]:
    sid = _map(map_key)
    if not sid:
        return None
    try:
        val = _kw(_f(get_sensor_value(sid), 0.0))
        return float(val)
    except Exception:
        return None

def _battery_power_kw_from_config() -> Optional[float]:
    """
    Liefert Batterie-Leistung in kW:
      >0 = ENTLAEDUNG (liefert Energie ins Haus)
      <0 = LADUNG     (verbraucht Energie)
    Hinweis: Dein Battery-Store kommentiert i>0 = LADUNG, i<0 = ENTLADUNG.
    Wir drehen das Vorzeichen, damit ENTLADUNG positiv ist.
    """
    try:
        p_ent = effective_entity_key((bat_get("power_entity", "") or "").strip(), DEV_BATTERY_POWER)
        if p_ent:
            p = _f(get_sensor_value(p_ent), None)
            if p is not None:
                return -float(_kw(p))

        v_ent = effective_entity_key((bat_get("voltage_entity", "") or "").strip(), DEV_BATTERY_VOLTAGE)
        i_ent = effective_entity_key((bat_get("current_entity", "") or "").strip(), DEV_BATTERY_CURRENT)
        if v_ent and i_ent:
            v = _f(get_sensor_value(v_ent), None)
            i = _f(get_sensor_value(i_ent), None)
            if v is None or i is None:
                return None
            return -(v * i) / 1000.0  # ENTLADUNG > 0
    except Exception:
        pass
    return None

def _controllable_now_kw() -> float:
    """Schätzt aktuell laufende, von uns kontrollierbare Last (kW)."""
    now_kw = 0.0
    # Heater (aus Prozent × Max-Leistung)
    try:
        from services.heater_store import resolve_entity_id as heat_resolve, get_var as heat_get
        he_id = effective_entity_key((heat_resolve("input_heizstab_cache") or "").strip(), DEV_HEATER_PERCENT)
        maxp = _f(heat_get("max_power_heater", 0.0), 0.0)
        if he_id and maxp > 0.0:
            pct = _f(get_sensor_value(he_id), 0.0)
            now_kw += max(0.0, maxp) * max(0.0, min(100.0, pct)) / 100.0
    except Exception:
        pass

    # Cooling (diskret)
    try:
        from services.cooling_store import get_cooling
        c = get_cooling() or {}
        pkw = _f(c.get("power_kw"), 0.0)
        is_on = bool(c.get("on"))
        if is_on and pkw > 0.0:
            now_kw += pkw
    except Exception:
        pass

    # Miner (diskret)
    try:
        from services.miners_store import list_miners
        for m in (list_miners() or []):
            if bool(m.get("on")):
                now_kw += _f(m.get("power_kw"), 0.0)
    except Exception:
        pass

    return max(0.0, now_kw)

def read_energy_flows() -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Liefert: (pv_kw, imp_kw, feed_kw, bat_kw, surplus_direct_kw)
      - bat_kw   >0 = Batterie ENTLAEDT; <0 = LAEDT
      - surplus_direct_kw: direkter Überschuss-Sensor (>=0), falls gemappt (optional)
    """
    pv_id   = _map("pv_production")
    imp_id  = _map("grid_consumption")
    feed_id = _map("grid_feed_in")

    pv   = _kw(_f(get_sensor_value(pv_id), 0.0))   if pv_id   else None
    imp  = _kw(_f(get_sensor_value(imp_id), 0.0))  if imp_id  else None
    feed = _kw(_f(get_sensor_value(feed_id), 0.0)) if feed_id else None
    if feed is not None and feed < 0:
        feed = abs(feed)

    bat  = _battery_power_kw_from_config()
    surplus_direct = _read_opt_kw("pv_surplus")
    if surplus_direct is not None:
        surplus_direct = max(0.0, surplus_direct)

    return pv, imp, feed, bat, surplus_direct

def surplus_strict_kw() -> Tuple[float, float, float, float, float]:
    """
    Liefert (surplus_raw, total_load, ctrl_now, base_load, pv)
    surplus_raw ist echter PV-Überschuss OHNE Batterie-Entladung.
    """
    pv_v, imp_v, feed_v, bat_v, surplus_direct = read_energy_flows()

    pv    = max(pv_v or 0.0, 0.0)
    imp   = max(imp_v or 0.0, 0.0)
    feed  = max(feed_v or 0.0, 0.0)
    bat   = float(bat_v or 0.0)  # >0 = Entladung, <0 = Ladung

    bat_discharge = max(0.0, bat)                 # nur Entladung
    total_load = max(0.0, pv + imp + bat_discharge - feed)

    ctrl_now  = _controllable_now_kw()
    base_load = max(0.0, total_load - ctrl_now)

    if surplus_direct is not None:
        surplus_raw = max(0.0, float(surplus_direct))
    else:
        surplus_raw = max(feed, pv - base_load)

    return surplus_raw, total_load, ctrl_now, base_load, pv

def incremental_mix_for(delta_kw: float) -> tuple[float, float, float]:
    """
    Für eine zusätzliche Last ΔP gibt (pv_share, grid_share, pv_kw) zurück.
    Nutzt die strikte Überschusslogik (Batterie-Entladung zählt NICHT als PV).
    """
    delta = max(0.0, float(delta_kw))
    if delta == 0.0:
        return 0.0, 0.0, 0.0
    surplus_raw, *_ = surplus_strict_kw()
    pv_kw = max(0.0, min(surplus_raw, delta))
    pv_share = pv_kw / delta
    grid_share = 1.0 - pv_share
    return pv_share, grid_share, pv_kw
