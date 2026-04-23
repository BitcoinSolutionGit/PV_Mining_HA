# services/consumers/miner.py
from __future__ import annotations

import time
from typing import Optional

from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour
from services.consumers.base import BaseConsumer, Desire, Ctx
from services.cooling_store import get_cooling, set_cooling
from services.electricity_store import current_price as elec_price
from services.electricity_store import get_var as elec_get
from services.ha_entities import call_action
from services.ha_sensors import get_sensor_value
from services.license import is_premium_enabled
from services.miners_store import list_miners, request_miner_state
from services.settings_store import get_var as set_get


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


def _cfg_num(path: str, default: float) -> float:
    try:
        return float(set_get(path, default) or default)
    except Exception:
        return default


def _free_miner_id() -> Optional[str]:
    try:
        miners = list_miners() or []
        if not miners:
            return None
        return miners[0].get("id")
    except Exception:
        return None


def _pv_cost_per_kwh() -> float:
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0

    mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    if mode == "sensor":
        sens = set_get("feedin_price_sensor", "") or ""
        try:
            tarif = _num(get_sensor_value(sens), 0.0) if sens else 0.0
        except Exception:
            tarif = _num(set_get("feedin_price_value", 0.0), 0.0)
    else:
        tarif = _num(set_get("feedin_price_value", 0.0), 0.0)

    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    return max(tarif - fee_up, 0.0)


def _on_fraction_for_miner(miner_id: str, default: float = 0.95) -> float:
    for key in (
        f"miner.{miner_id}.on_fraction",
        "miner.on_fraction",
        "miner_on_fraction",
        "discrete_on_fraction",
    ):
        try:
            value = set_get(key, None)
            if value is None or str(value).strip() == "":
                continue
            frac = float(value)
            if frac > 1.0:
                frac = frac / 100.0
            return max(0.0, min(1.0, frac))
        except Exception:
            pass
    return default


def _cooling_required(m: dict) -> bool:
    flags = [
        m.get("require_cooling"),
        m.get("cooling_required"),
        m.get("needs_cooling"),
        (m.get("cooling") or {}).get("required") if isinstance(m.get("cooling"), dict) else None,
    ]
    return any(_truthy(flag) for flag in flags)


def _cooling_power_kw() -> float:
    try:
        c = get_cooling() or {}
        return _num(c.get("power_kw"), 0.0)
    except Exception:
        return 0.0


def _cooling_running_strict() -> Optional[bool]:
    try:
        c = get_cooling() or {}
        ha = c.get("ha_on")
        if ha is None:
            return None
        return bool(ha)
    except Exception:
        return None


def _cooling_running_now() -> bool:
    try:
        c = get_cooling() or {}
        if "ha_on" in c and c["ha_on"] is not None:
            return bool(c["ha_on"])
        rs_id = (c.get("ready_entity") or c.get("ready_state_entity") or c.get("state_entity") or "").strip()
        if rs_id:
            return _truthy(get_sensor_value(rs_id), False)
        return _truthy(c.get("effective_on"), False) or _truthy(c.get("on"), False)
    except Exception:
        return False


def _cooling_auto_available() -> bool:
    try:
        c = get_cooling() or {}
        if not _truthy(set_get("cooling_feature_enabled", False), False):
            return False
        if not _truthy(c.get("enabled"), True):
            return False
        if str(c.get("mode") or "manual").lower() != "auto":
            return False
        if not (c.get("ready_entity") or "").strip():
            return False
        return _num(c.get("power_kw"), 0.0) > 0.0
    except Exception:
        return False


def _cooling_effective_on() -> bool:
    try:
        c = get_cooling() or {}
        return (
            _truthy(c.get("effective_on"), False)
            or _truthy(c.get("pending_on"), False)
            or _truthy(c.get("on"), False)
        )
    except Exception:
        return False


def _cooling_permits_miner_start() -> tuple[bool, str]:
    """
    Safety-critical rule:
    cooling-dependent miners may start only with an explicit ready signal.
    """
    try:
        c = get_cooling() or {}
        ready_entity = (c.get("ready_entity") or "").strip()
        phase = str(c.get("phase") or "").strip().lower()
        ha_on = c.get("ha_on")

        if not ready_entity:
            return False, "cooling ready sensor missing"
        if ha_on is True:
            return True, "cooling ready"
        if phase == "starting":
            return False, "cooling starting"
        if phase == "stopping":
            return False, "cooling stopping"
        return False, "cooling not ready"
    except Exception as e:
        return False, f"cooling state unknown: {e}"


def _cooling_startup_grace_s(c: Optional[dict] = None, default: int = 60) -> int:
    try:
        raw = (c or {}).get("ready_timeout_s")
        if raw is None or str(raw).strip() == "":
            raw = default
        return max(int(float(raw)), default)
    except Exception:
        return default


def _request_cooling_on(now_ts: float) -> tuple[bool, str]:
    try:
        c = get_cooling() or {}
        if not _truthy(set_get("cooling_feature_enabled", False), False):
            return False, "cooling feature disabled"
        if not _truthy(c.get("enabled"), True):
            return False, "cooling disabled"
        if str(c.get("mode") or "manual").lower() != "auto":
            return False, "cooling manual mode"

        if _cooling_effective_on():
            return True, "cooling already on"

        on_ent = (c.get("action_on_entity") or "").strip()
        ha_raw = c.get("ha_on")
        if on_ent:
            call_action(on_ent, True)

        set_cooling(
            on=True,
            pending_on=(ha_raw is not None),
            pending_off=False,
            startup_grace_until=(now_ts + _cooling_startup_grace_s(c)) if ha_raw is not None else 0.0,
            last_transition_ts=now_ts,
        )
        return True, "cooling requested on"
    except Exception as e:
        return False, f"cooling request failed: {e}"


def _miner_record(miner_id: str) -> Optional[dict]:
    for miner in (list_miners() or []):
        if miner.get("id") == miner_id:
            return miner
    return None


class MinerConsumer(BaseConsumer):
    def __init__(self, miner_id: Optional[str] = None) -> None:
        self.miner_id = miner_id or ""

    @property
    def id(self) -> str:
        return f"miner:{self.miner_id}" if self.miner_id else "miner"

    @property
    def label(self) -> str:
        custom = set_get(f"miner.{self.miner_id}.label", None)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()

        record = _miner_record(self.miner_id) or {}
        name = record.get("name")
        if bool(record.get("is_miner", True)):
            return f"Miner {name or self.miner_id or '?'}"
        return f"Consumer {name or self.miner_id or '?'}"

    def compute_desire(self, ctx: Ctx) -> Desire:
        record = _miner_record(self.miner_id)
        if not record:
            return Desire(False, 0.0, 0.0, reason="not found")

        if not is_premium_enabled():
            free_id = _free_miner_id()
            if record.get("id") != free_id:
                return Desire(False, 0.0, 0.0, reason="premium required")

        if not _truthy(record.get("enabled"), False):
            return Desire(False, 0.0, 0.0, reason="disabled")

        mode = str(record.get("mode") or "manual").lower()
        if mode != "auto":
            return Desire(False, 0.0, 0.0, reason="manual mode")

        is_miner = bool(record.get("is_miner", True))
        ths = _num(record.get("hashrate_ths"), 0.0)
        pkw = _num(record.get("power_kw"), 0.0)
        is_on_now = bool(record.get("on"))

        if pkw <= 0.0 or (is_miner and ths <= 0.0):
            return Desire(False, 0.0, 0.0, reason="no hashrate/power")

        need_cool = _cooling_required(record)
        cool_on = _cooling_running_now()
        if need_cool and not _cooling_auto_available():
            return Desire(False, 0.0, 0.0, reason="cooling unavailable")
        if need_cool and is_on_now and not cool_on:
            return Desire(False, 0.0, 0.0, reason="cooling lost")

        cooling_effective = _cooling_effective_on() if need_cool else False
        cool_kw = _cooling_power_kw() if need_cool else 0.0
        delta_kw = pkw + (cool_kw if (need_cool and not cooling_effective) else 0.0)

        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)
        on_margin = _cfg_num("miner_profit_on_eur_h", 0.05)
        off_margin = _cfg_num("miner_profit_off_eur_h", -0.01)

        if is_miner:
            sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
            sats_per_h = sat_th_h * ths
            eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
            revenue_eur_h = sats_per_h * eur_per_sat
            after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))
        else:
            after_tax = 0.0

        eff_grid_cost = _num(elec_price(), 0.0) + _num(elec_get("network_fee_down_value", 0.0), 0.0)
        if eff_grid_cost <= 0.0:
            reason = "negative grid price"
            if need_cool and not cooling_effective:
                reason = f"{reason} | cooling bundled"
            return Desire(True, 0.0, delta_kw, exact_kw=delta_kw, reason=reason)

        pv_cost = _pv_cost_per_kwh()
        pv_share = min(1.0, max(0.0, _num(ctx.get("surplus_kw", 0.0) if isinstance(ctx, dict) else getattr(ctx, "surplus_kw", 0.0), 0.0) / max(delta_kw, 1e-9)))
        grid_share = max(0.0, 1.0 - pv_share)
        blended_eur_per_kwh = pv_share * pv_cost + grid_share * eff_grid_cost

        cool_share_eur_h = 0.0
        if need_cool and not cooling_effective and cool_kw > 0.0:
            cool_share_eur_h = cool_kw * blended_eur_per_kwh

        total_cost_h = pkw * blended_eur_per_kwh + cool_share_eur_h

        if grid_share <= 1e-6:
            reason = "pv_only_ok"
            if need_cool and not cooling_effective:
                reason = f"{reason} | cooling bundled"
            return Desire(True, 0.0, delta_kw, exact_kw=delta_kw, reason=reason)

        if not is_miner:
            return Desire(False, 0.0, 0.0, reason="consumer: positive grid share")

        profit = after_tax - total_cost_h
        if is_on_now:
            if profit <= off_margin:
                return Desire(False, 0.0, 0.0, reason=f"not profitable (delta={profit:.2f} EUR/h <= off_margin)")
            reason = f"keep on (delta={profit:.2f} EUR/h)"
            if need_cool and not cooling_effective:
                reason = f"{reason} | cooling bundled"
            return Desire(True, 0.0, delta_kw, exact_kw=delta_kw, reason=reason)

        if profit >= on_margin:
            reason = f"profitable (delta={profit:.2f} EUR/h >= on_margin)"
            if need_cool and not cooling_effective:
                reason = f"{reason} | cooling bundled"
            return Desire(True, 0.0, delta_kw, exact_kw=delta_kw, reason=reason)
        return Desire(False, 0.0, 0.0, reason=f"not profitable (delta={profit:.2f} EUR/h < on_margin)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        record = _miner_record(self.miner_id)
        if not record:
            print(f"[miner {self.miner_id}] apply skipped: not found", flush=True)
            return

        if not is_premium_enabled():
            free_id = _free_miner_id()
            if record.get("id") != free_id:
                print(f"[miner {self.miner_id}] premium required - skipping apply", flush=True)
                return

        mode = str(record.get("mode") or "manual").lower()
        if mode != "auto":
            return

        pkw = _num(record.get("power_kw"), 0.0)
        prev_on = bool(record.get("on"))

        frac = _on_fraction_for_miner(self.miner_id, default=0.95)
        should_on = pkw > 0.0 and alloc_kw >= frac * pkw
        print(f"[miner {self.miner_id}] on_fraction={frac:.2f} alloc={alloc_kw:.3f} pkw={pkw:.3f}", flush=True)

        need_cool = _cooling_required(record)
        if should_on and need_cool:
            cool_ok, cool_reason = _cooling_permits_miner_start()
            if not cool_ok:
                ok, reason = _request_cooling_on(time.time())
                print(
                    f"[miner {self.miner_id}] cooling dependency -> {cool_reason}; "
                    f"request={reason} ok={ok}",
                    flush=True,
                )
                should_on = False

        try:
            if should_on and not prev_on:
                ok, reason = request_miner_state(self.miner_id, True, now_ts=time.time(), enforce_runtime=True)
                print(f"[miner {self.miner_id}] apply ~{alloc_kw:.2f} kW (ON) ok={ok} reason={reason}", flush=True)
            elif (not should_on) and prev_on:
                ok, reason = request_miner_state(self.miner_id, False, now_ts=time.time(), enforce_runtime=True)
                print(f"[miner {self.miner_id}] apply 0 kW (OFF) ok={ok} reason={reason}", flush=True)
        except Exception as e:
            print(f"[miner {self.miner_id}] apply error: {e}", flush=True)
