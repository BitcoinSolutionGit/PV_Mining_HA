# services/consumers/miner.py
from __future__ import annotations
from typing import Dict, Any, Optional
from .base import Consumer, Desire, Ctx

from services.miners_store import list_miners
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.ha_sensors import get_sensor_value
from services.utils import load_yaml
from services.btc_metrics import (
    get_live_btc_price_eur,
    get_live_network_hashrate_ths,
    sats_per_th_per_hour,
)
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

def _find_miner(mid: str) -> Optional[dict]:
    for m in (list_miners() or []):
        if str(m.get("id")) == mid:
            return m
    return None

def _pv_cost_per_kwh() -> float:
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0
    mode = (set_get("feedin_price_mode","fixed") or "fixed").lower()
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    if mode == "sensor":
        sens = set_get("feedin_price_sensor","") or ""
        tarif = _num(get_sensor_value(sens) if sens else 0.0, 0.0)
    else:
        tarif = _num(set_get("feedin_price_value",0.0),0.0)
    return max(tarif - fee_up, 0.0)

class MinerConsumer(Consumer):
    """
    Consumer-ID-Form: 'miner:<miner_id>'  (z.B. miner:m_abcd1234)
    """
    id = "miner"
    label = "Miner"

    def __init__(self, miner_id: str):
        super().__init__()
        self.miner_id = miner_id

    # -------- core: Profit-Check & Desire --------
    def compute_desire(self, ctx: Ctx) -> Desire:
        m = _find_miner(self.miner_id)
        if not m:
            return Desire(False, 0.0, 0.0, reason="miner not found")
        if not m.get("enabled", True):
            return Desire(False, 0.0, 0.0, reason="miner disabled")
        if str(m.get("mode","manual")).lower() != "auto":
            return Desire(False, 0.0, 0.0, reason="miner not in auto")

        ths = _num(m.get("hashrate_ths"), 0.0)
        pkw = _num(m.get("power_kw"), 0.0)
        if ths <= 0.0 or pkw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="missing hashrate/power")

        # Cooling-Voraussetzungen
        require_cooling = bool(m.get("require_cooling"))
        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        cooling = get_cooling() if cooling_feature else {}
        cooling_mode_auto = (str((cooling or {}).get("mode","")).lower() == "auto")
        cooling_on = bool((cooling or {}).get("on"))
        cooling_kw = _num((cooling or {}).get("power_kw"), 0.0)

        # Wenn Miner Cooling braucht, Cooling aber manuell ist → kein Auto-Wunsch
        if cooling_feature and require_cooling and not cooling_mode_auto:
            return Desire(False, 0.0, 0.0, reason="cooling manual")

        # --- Live Economics / Fallbacks ---
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)
        sat_th_h = sats_per_th_per_hour(reward, net_ths)
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0

        sats_per_h = sat_th_h * ths
        revenue_eur_h = sats_per_h * eur_per_sat
        after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

        # --- Inkrementeller Mix (wie in miners.py KPIs) ---
        pv_id   = _map_id("pv_production")
        grid_id = _map_id("grid_consumption")
        feed_id = _map_id("grid_feed_in")
        pv_val   = _num(get_sensor_value(pv_id), 0.0)
        grid_val = _num(get_sensor_value(grid_id), 0.0)
        feed_val = max(_num(get_sensor_value(feed_id), 0.0), 0.0)

        base = elec_price() or 0.0
        fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)
        pv_cost = _pv_cost_per_kwh()

        # Falls Cooling benötigt und (noch) nicht an, tue so als käme dessen kW dazu
        delta_kw = pkw + (cooling_kw if (cooling_feature and require_cooling and not cooling_on) else 0.0)

        if delta_kw > 0.0:
            pv_share_add = max(min(feed_val / delta_kw, 1.0), 0.0)
        else:
            pv_share_add = 0.0
        grid_share_add = 1.0 - pv_share_add
        blended_eur_per_kwh = pv_share_add * pv_cost + grid_share_add * (base + fee_down)

        # Cooling-Kosten anteilig (aktive + dieser Miner)
        cool_share = 0.0
        if cooling_feature and require_cooling and cooling_kw > 0.0:
            active = [mx for mx in (list_miners() or [])
                      if mx.get("enabled") and mx.get("on") and mx.get("require_cooling")]
            n_future = len(active) + 1  # inkl. diesem Miner
            cool_share = (cooling_kw * blended_eur_per_kwh) / max(n_future, 1)

        cost_eur_h = pkw * blended_eur_per_kwh
        total_cost_h = cost_eur_h + cool_share
        profit = after_tax - total_cost_h

        if profit > 0.0:
            # Miner ist binär → exakte Blockleistung
            return Desire(True, pkw, pkw, must_run=False, exact_kw=pkw,
                          reason=f"profitable (+{profit:.2f} €/h)")
        return Desire(False, 0.0, 0.0, reason=f"unprofitable ({profit:.2f} €/h)")

    # Wir schalten Miner erst im „apply“-Schritt der Pipeline (später)
    def apply(self, allocated_kw: float, ctx: Ctx) -> None:
        return
