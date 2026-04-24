# services/consumers/cooling.py
from __future__ import annotations

import time

from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour
from services.consumers.base import BaseConsumer, Desire, Ctx
from services.cooling_store import get_cooling, set_cooling
from services.electricity_store import current_price as elec_price
from services.electricity_store import get_var as elec_get
from services.energy_mix import incremental_mix_for
from services.ha_entities import call_action
from services.settings_store import get_var as set_get
from services.miners_store import list_miners

_last_cmd: str | None = None
_last_cmd_ts: float = 0.0


def _can_send(cmd: str, now_ts: float, cooldown_s: float) -> bool:
    global _last_cmd, _last_cmd_ts
    if _last_cmd == cmd and (now_ts - _last_cmd_ts) < cooldown_s:
        return False
    _last_cmd = cmd
    _last_cmd_ts = now_ts
    return True


def _truthy(x, default=False) -> bool:
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1", "true", "on", "yes", "y", "auto", "enabled"):
        return True
    try:
        return float(s) > 0.0
    except Exception:
        return False


def _num(x, d=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _requires_cooling(m: dict) -> bool:
    flags = [
        m.get("require_cooling"),
        m.get("cooling_required"),
        m.get("needs_cooling"),
        (m.get("cooling") or {}).get("required") if isinstance(m.get("cooling"), dict) else None,
    ]
    return any(_truthy(flag) for flag in flags)


def _pv_cost_per_kwh() -> float:
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0
    mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    if mode == "sensor":
        sens = set_get("feedin_price_sensor", "") or ""
        try:
            from services.ha_sensors import get_sensor_value

            price = _num(get_sensor_value(sens), 0.0) if sens else 0.0
        except Exception:
            price = _num(set_get("feedin_price_value", 0.0), 0.0)
    else:
        price = _num(set_get("feedin_price_value", 0.0), 0.0)
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    return max(price - fee_up, 0.0)


def _startup_grace_s(c: dict | None = None, default: int = 60) -> int:
    try:
        raw = (c or {}).get("ready_timeout_s")
        if raw is None or str(raw).strip() == "":
            raw = default
        return max(int(float(raw)), default)
    except Exception:
        return default


class CoolingConsumer(BaseConsumer):
    id = "cooling"
    label = "Cooling circuit"

    def compute_desire(self, ctx: Ctx) -> Desire:
        feature = bool(set_get("cooling_feature_enabled", False))
        if not feature:
            return Desire(False, 0.0, 0.0, reason="feature disabled")

        c = get_cooling() or {}
        enabled = _truthy(c.get("enabled"), True)
        mode = str(c.get("mode") or "manual").lower()
        power_kw = _num(c.get("power_kw"), 0.0)
        pending_on = _truthy(c.get("pending_on"), False)
        pending_off = _truthy(c.get("pending_off"), False)
        startup_grace_until = _num(c.get("startup_grace_until"), 0.0)
        startup_grace_active = pending_on and not pending_off and (startup_grace_until <= 0.0 or time.time() < startup_grace_until)

        if not enabled:
            return Desire(False, 0.0, 0.0, reason="disabled")
        if power_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no power configured")
        if mode != "auto":
            return Desire(False, 0.0, 0.0, reason="manual mode")

        if startup_grace_active:
            return Desire(True, power_kw, power_kw, exact_kw=power_kw, reason="startup grace")

        try:
            active_need = any(
                _truthy(m.get("effective_on", m.get("on")), False) and _requires_cooling(m)
                for m in (list_miners() or [])
            )
        except Exception:
            active_need = False
        if active_need:
            return Desire(True, power_kw, power_kw, exact_kw=power_kw, reason="serve active cooling miners")

        try:
            candidates = [
                m for m in (list_miners() or [])
                if _truthy(m.get("enabled"), False)
                and str(m.get("mode") or "manual").lower() == "auto"
                and _requires_cooling(m)
                and _num(m.get("power_kw"), 0.0) > 0.0
                and _num(m.get("hashrate_ths"), 0.0) > 0.0
            ]
        except Exception:
            candidates = []
        if not candidates:
            return Desire(False, 0.0, 0.0, reason="no miner requires cooling")

        eff_grid_cost = _num(elec_price(), 0.0) + _num(elec_get("network_fee_down_value", 0.0), 0.0)
        if eff_grid_cost <= 0.0:
            return Desire(True, power_kw, power_kw, exact_kw=power_kw, reason="negative grid price with candidates")

        pv_cost = _pv_cost_per_kwh()
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)
        sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
        is_running = _truthy(c.get("effective_on"), False) or _truthy(c.get("on"), False)

        for miner in candidates:
            miner_kw = _num(miner.get("power_kw"), 0.0)
            ths = _num(miner.get("hashrate_ths"), 0.0)
            delta = miner_kw + (0.0 if is_running else power_kw)
            if delta <= 0.0:
                continue

            pv_share, grid_share, _ = incremental_mix_for(delta)
            blended = pv_share * pv_cost + grid_share * eff_grid_cost
            revenue_eur_h = (sat_th_h * ths) * eur_per_sat
            after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))
            total_cost = delta * blended

            if grid_share <= 1e-6 or after_tax >= total_cost:
                reason = "pv_only_ok" if grid_share <= 1e-6 else f"profitable (delta={after_tax - total_cost:.2f} EUR/h)"
                return Desire(True, power_kw, power_kw, exact_kw=power_kw, reason=reason)

        return Desire(False, 0.0, 0.0, reason="no qualifying miner (pv/profit)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        c = get_cooling() or {}
        mode = str(c.get("mode") or "manual").lower()
        if mode != "auto":
            return

        power_kw = _num(c.get("power_kw"), 0.0)
        on_ent = (c.get("action_on_entity") or "").strip()
        off_ent = (c.get("action_off_entity") or "").strip()
        ha_raw = c.get("ha_on")
        running = _truthy(c.get("effective_on"), False) if "effective_on" in c else (bool(ha_raw) if ha_raw is not None else _truthy(c.get("on"), False))
        pending_on = _truthy(c.get("pending_on"), False)
        pending_off = _truthy(c.get("pending_off"), False)
        should_on = power_kw > 0.0 and alloc_kw > 0.0

        now_ts = time.time()
        cooldown = 0.8

        try:
            if should_on and not running and not pending_on:
                if on_ent and _can_send("on", now_ts, cooldown):
                    call_action(on_ent, True)
                set_cooling(
                    on=True,
                    pending_on=(ha_raw is not None),
                    pending_off=False,
                    startup_grace_until=(now_ts + _startup_grace_s(c)) if ha_raw is not None else 0.0,
                    last_transition_ts=now_ts,
                )
                print(f"[cooling] AUTO request ON (~{alloc_kw:.2f} kW)", flush=True)
            elif (not should_on) and (running or pending_on or pending_off):
                if off_ent and _can_send("off", now_ts, cooldown):
                    call_action(off_ent, False)
                set_cooling(
                    on=False,
                    pending_on=False,
                    pending_off=(ha_raw is not None and running),
                    startup_grace_until=0.0,
                    last_transition_ts=now_ts,
                )
                print(f"[cooling] AUTO request OFF (~{alloc_kw:.2f} kW)", flush=True)
        except Exception as e:
            print(f"[cooling] apply error (auto): {e}", flush=True)
