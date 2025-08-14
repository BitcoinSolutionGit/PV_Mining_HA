# services/btc_metrics.py
import os
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.settings_store import get_var as set_get, set_vars as set_set
from services.forex import usd_to_eur_rate

CONFIG_DIR = "/config/pv_mining_addon"
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

def _to_float(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

def _resolve_entity_or_number(val):
    """val kann eine Entity-ID (sensor.xyz) ODER bereits eine Zahl sein."""
    if isinstance(val, str) and val.startswith(("sensor.", "number.", "input_number.")):
        return _to_float(get_sensor_value(val), 0.0)
    return _to_float(val, 0.0)

def get_live_btc_price_eur(fallback=0.0) -> float:
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    raw = ents.get("sensor_btc_price")
    price = _resolve_entity_or_number(raw)

    # Währung aus Settings (Default: EUR)
    cur = str(set_get("btc_price_currency", "EUR") or "EUR").upper()
    if cur == "USD":
        fx = usd_to_eur_rate(fallback=_to_float(set_get("fx_usd_to_eur", 0.93), 0.93))
        price *= fx
        # optional: letzten guten Kurs persistieren
        if fx > 0:
            set_set(fx_usd_to_eur=fx)

    return price if price > 0 else _to_float(fallback, 0.0)

def _normalize_network_hashrate_to_ths(v: float) -> float:
    """
    Normalisiert Netzwerk-Hashrate auf TH/s.
    Heuristik nach Größenordnung:
      ~600 EH/s => Zahl ~600 -> *1e6
      ~6e8 TH/s => Zahl ~6e8 -> passt
      ~6e20 H/s => Zahl >1e12 -> /1e12
    """
    if v <= 0: return 0.0
    if v < 1e5:     # vermutlich EH/s
        return v * 1e6
    if v > 1e12:    # vermutlich H/s
        return v / 1e12
    return v        # schon TH/s

def get_live_network_hashrate_ths(fallback=0.0) -> float:
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    raw = ents.get("sensor_btc_hashrate")
    v = _resolve_entity_or_number(raw)
    v_ths = _normalize_network_hashrate_to_ths(v)
    if v_ths > 0: return v_ths
    # Fallback akzeptiert beliebige Einheit; normalisieren:
    return _normalize_network_hashrate_to_ths(_to_float(fallback, 0.0))

def sats_per_th_per_hour(block_reward_btc: float, network_hashrate_ths: float) -> float:
    if network_hashrate_ths <= 0: return 0.0
    return _to_float(block_reward_btc, 0.0) * 6.0 * 1e8 / network_hashrate_ths

def get_live_btc_price_eur(fallback=0.0) -> float:
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    raw = ents.get("sensor_btc_price")
    price = _resolve_entity_or_number(raw)

    # Währung aus Settings lesen (Default EUR)
    cur = str(set_get("btc_price_currency", "EUR") or "EUR").upper()
    if cur == "USD":
        fx = _to_float(set_get("fx_usd_to_eur", 0.93), 0.93)
        price = price * fx

    return price if price > 0 else _to_float(fallback, 0.0)
