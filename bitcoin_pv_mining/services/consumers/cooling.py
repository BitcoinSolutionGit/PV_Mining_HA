# services/consumers/cooling.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .base import Consumer, Desire, Ctx, now
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from services.miners_store import list_miners
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.ha_sensors import get_sensor_value
from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def _pv_cost_per_kwh() -> float:
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0
    mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    if mode == "sensor":
        sens = set_get("feedin_price_sensor", "") or ""
        tarif = _num(get_sensor_value(sens) if sens else 0.0, 0.0)
    else:
        tarif = _num(set_get("feedin_price_value", 0.0), 0.0)
    return max(tarif - fee_up, 0.0)

def _shares_for_delta_kw(delta_kw: float, ctx: Ctx) -> tuple[float, float]:
    if delta_kw <= 0:
        return 0.0, 1.0
    # wir nutzen bevorzugt ctx['feed_in_kw']; wenn nicht vorhanden, 0
    feed_in = _num(ctx.get("feed_in_kw", 0.0), 0.0)
    pv_share_add = max(min(feed_in / delta_kw, 1.0), 0.0)
    grid_share_add = 1.0 - pv_share_add
    return pv_share_add, grid_share_add

def _is_profitable_for_start(miner: Dict[str, Any], cooling_running_now: bool, ctx: Ctx) -> bool:
    ths = _num(miner.get("hashrate_ths"), 0.0)
    pkw = _num(miner.get("power_kw"), 0.0)
    if ths <= 0.0 or pkw <= 0.0:
        return False

    btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
    net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
    reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
    tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

    sat_th_h   = sats_per_th_per_hour(reward, net_ths)
    sats_per_h = sat_th_h * ths
    eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
    revenue_eur_h = sats_per_h * eur_per_sat
    after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

    base     = elec_price() or 0.0
    fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)
    pv_cost  = _pv_cost_per_kwh()

    cooling = ctx.get("cooling") or get_cooling() or {}
    cooling_kw_cfg = _num(cooling.get("power_kw"), 0.0)

    require_cooling = bool(miner.get("require_cooling"))
    delta_kw = pkw + (cooling_kw_cfg if (require_cooling and not cooling_running_now) else 0.0)

    pv_share_add, grid_share_add = _shares_for_delta_kw(delta_kw, ctx)
    blended_eur_per_kwh = pv_share_add * pv_cost + grid_share_add * (base + fee_down)

    # cooling-share fair (aktive + dieser)
    cool_share = 0.0
    if require_cooling and cooling_kw_cfg > 0.0:
        active = [mx for mx in (list_miners() or []) if mx.get("enabled") and mx.get("on") and mx.get("require_cooling")]
        n_future = len(active) + 1
        cool_share = (cooling_kw_cfg * blended_eur_per_kwh) / max(n_future, 1)

    cost_eur_h   = pkw * blended_eur_per_kwh
    total_cost_h = cost_eur_h + cool_share
    return (after_tax - total_cost_h) > 0.0

class CoolingConsumer:
    id = "cooling"
    label = "Cooling circuit"

    def _cfg(self) -> Dict[str, Any]:
        return get_cooling() or {}

    def _feature_on(self) -> bool:
        return bool(set_get("cooling_feature_enabled", False))

    def compute_desire(self, ctx: Ctx) -> Desire:
        if not self._feature_on():
            return Desire(False, 0.0, 0.0, reason="feature disabled")

        c = self._cfg()
        power_kw = _num(c.get("power_kw"), 0.0)
        mode = (c.get("mode") or "").lower()
        on_now = bool(c.get("on"))
        cooling_running_now = bool(c.get("on"))

        # MANUAL: respektiere festen Schalter
        if mode not in ("auto", "automatic"):
            if on_now and power_kw > 0:
                return Desire(True, power_kw, power_kw, must_run=True, exact_kw=power_kw, reason="manual=on")
            return Desire(False, 0.0, 0.0, reason="manual=off")

        # AUTO: nur wenn mind. 1 Auto-Miner mit Cooling-Pflicht profitabel wäre
        profitable = False
        for m in (list_miners() or []):
            if not m.get("enabled"):                continue
            if (m.get("mode") or "").lower() != "auto":  continue
            if not m.get("require_cooling"):       continue
            if _is_profitable_for_start(m, cooling_running_now, ctx):
                profitable = True
                break

        if profitable and power_kw > 0:
            return Desire(True, power_kw, power_kw, must_run=False, exact_kw=power_kw, reason="auto: profitable miner needs cooling")
        return Desire(False, 0.0, 0.0, reason="auto: no profitable miner needs cooling")

    def apply(self, allocated_kw: float, ctx: Ctx) -> None:
        """In Schritt 3 noch kein Eingriff – Orchestrator ist Dry-Run."""
        return
