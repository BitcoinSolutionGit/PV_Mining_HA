# services/consumers/miner.py
from __future__ import annotations

import time
from typing import Optional, List

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.license import is_premium_enabled
from services.miners_store import list_miners, update_miner
from services.settings_store import get_var as set_get
from services.electricity_store import get_var as elec_get
from services.electricity_store import current_price as elec_price
from services.ha_entities import call_action
from services.btc_metrics import (
    get_live_btc_price_eur,
    get_live_network_hashrate_ths,
    sats_per_th_per_hour,
)
from services.energy_mix import incremental_mix_for
from services.ha_sensors import get_sensor_value


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
    """Erster Eintrag in der Miners-Liste (= „freier“ Miner ohne Premium)."""
    try:
        miners = list_miners() or []
        if not miners:
            return None
        return miners[0].get("id")
    except Exception:
        return None


def _pv_cost_per_kwh() -> float:
    """Opportunitätskosten der PV gemäß Settings (zero | feedin)."""
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


def _cooling_required(m: dict) -> bool:
    flags = [
        m.get("require_cooling"),
        m.get("cooling_required"),
        m.get("needs_cooling"),
        (m.get("cooling") or {}).get("required") if isinstance(m.get("cooling"), dict) else None,
    ]
    return any(_truthy(f) for f in flags)


def _cooling_power_kw() -> float:
    try:
        from services.cooling_store import get_cooling
        c = get_cooling() or {}
        return _num(c.get("power_kw"), 0.0)
    except Exception:
        return 0.0


def _cooling_running_now() -> bool:
    """
    True, wenn Cooling laut Ready/State-Entity läuft (Fallback: 'on' Flag).
    """
    try:
        from services.cooling_store import get_cooling
        c = get_cooling() or {}
        rs_id = (c.get("ready_state_entity") or c.get("state_entity") or "").strip()
        if rs_id:
            return _truthy(get_sensor_value(rs_id), False)
        return _truthy(c.get("on"), False)
    except Exception:
        return False


def _eligible_miners() -> List[dict]:
    free_id = _free_miner_id()
    prem = is_premium_enabled()

    out = []
    for m in (list_miners() or []):
        if not prem and m.get("id") != free_id:
            continue
        if not _truthy(m.get("enabled"), False):
            continue
        if str(m.get("mode") or "manual").lower() != "auto":
            continue
        if _num(m.get("power_kw"), 0.0) <= 0.0 or _num(m.get("hashrate_ths"), 0.0) <= 0.0:
            continue
        out.append(m)
    return out


class MinerConsumer(BaseConsumer):
    def __init__(self, miner_id: Optional[str] = None) -> None:
        self.miner_id = miner_id or ""

    @property
    def id(self) -> str:
        return f"miner:{self.miner_id}" if self.miner_id else "miner"

    @property
    def label(self) -> str:
        name = None
        try:
            for m in list_miners() or []:
                if m.get("id") == self.miner_id:
                    name = m.get("name")
                    break
        except Exception:
            pass
        return f"Miner {name or self.miner_id or '?'}"

    def compute_desire(self, ctx: Ctx) -> Desire:
        # Datensatz suchen
        m = None
        for mx in (list_miners() or []):
            if mx.get("id") == self.miner_id:
                m = mx
                break
        if not m:
            return Desire(False, 0.0, 0.0, reason="not found")

        # --- Hysterese-/Zeit-Parameter ---
        on_margin = _cfg_num("miner_profit_on_eur_h", 0.05)    # Gewinnschwelle zum Einschalten
        off_margin = _cfg_num("miner_profit_off_eur_h", -0.01) # Schwelle zum Ausschalten
        min_run_s = int(_cfg_num("miner_min_run_s", 30))       # Mindestlaufzeit
        min_off_s = int(_cfg_num("miner_min_off_s", 20))       # Mindest-Auszeit

        now_ts = time.time()
        last_flip = float(m.get("last_flip_ts") or 0.0)
        is_on_now = bool(m.get("on"))

        # Premium-Gate
        if not is_premium_enabled():
            free_id = _free_miner_id()
            if m.get("id") != free_id:
                return Desire(False, 0.0, 0.0, reason="premium required")

        if not _truthy(m.get("enabled"), False):
            return Desire(False, 0.0, 0.0, reason="disabled")

        mode = str(m.get("mode") or "manual").lower()
        if mode != "auto":
            return Desire(False, 0.0, 0.0, reason="manual mode")

        ths = _num(m.get("hashrate_ths"), 0.0)
        pkw = _num(m.get("power_kw"), 0.0)
        if ths <= 0.0 or pkw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no hashrate/power")

        # Sicherheitsregel: Cooling muss laufen, wenn benötigt
        if _cooling_required(m) and not _cooling_running_now():
            if is_on_now:
                return Desire(False, 0.0, 0.0, reason="cooling lost")
            return Desire(False, 0.0, 0.0, reason="cooling not ready")

        # Sperrzeiten gegen Flattern
        if is_on_now and (now_ts - last_flip) < max(0, min_run_s):
            return Desire(
                True,
                pkw,
                pkw,
                must_run=True,
                exact_kw=pkw,
                reason=f"min-run lock {int(min_run_s - (now_ts - last_flip))}s",
            )
        if (not is_on_now) and (now_ts - last_flip) < max(0, min_off_s):
            return Desire(False, 0.0, 0.0, reason=f"min-off lock {int(min_off_s - (now_ts - last_flip))}s")

        # Live-Erlöse
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

        sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
        sats_per_h = sat_th_h * ths
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
        revenue_eur_h = sats_per_h * eur_per_sat
        after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

        # Kostenparameter
        pv_cost = _pv_cost_per_kwh()
        eff_grid_cost = _num(elec_price(), 0.0) + _num(elec_get("network_fee_down_value", 0.0), 0.0)

        # Negativer Netzpreis → „alles ziehen“
        if eff_grid_cost <= 0.0:
            return Desire(True, 0.0, pkw, must_run=False, exact_kw=pkw, reason="neg grid price")

        # Cooling-Bedarf/Zustand
        need_cool = _cooling_required(m)
        cool_on = _cooling_running_now()
        cool_kw = _cooling_power_kw() if need_cool else 0.0

        # ΔP für Mixberechnung: Miner + ggf. Cooling, falls Cooling noch aus ist
        delta_kw = pkw + (cool_kw if (need_cool and not cool_on) else 0.0)

        pv_share, grid_share, _pv_kw_for_delta = incremental_mix_for(delta_kw)
        blended_eur_per_kwh = pv_share * pv_cost + grid_share * eff_grid_cost

        # Cooling-Kosten fair anteilig, nur wenn Cooling durch diesen Miner zusätzlich starten müsste
        cool_share_eur_h = 0.0
        if need_cool and not cool_on and cool_kw > 0.0:
            active = [mx for mx in _eligible_miners() if _truthy(mx.get("on"), False) and _cooling_required(mx)]
            n_future = len(active) + 1  # inkl. diesem Miner
            cool_share_eur_h = (cool_kw / max(n_future, 1)) * blended_eur_per_kwh

        miner_cost_eur_h = pkw * blended_eur_per_kwh
        total_cost_h = miner_cost_eur_h + cool_share_eur_h

        # PV-only ist immer OK
        if grid_share <= 1e-6:
            return Desire(True, 0.0, pkw, must_run=False, exact_kw=pkw, reason="pv_only_ok")

        # Gewinn (nach Steuer) gegen Kosten
        profit = after_tax - total_cost_h

        # Entscheidung mit Hysterese
        if is_on_now:
            if profit <= off_margin:
                return Desire(False, 0.0, 0.0, reason=f"not profitable (Δ={profit:.2f} €/h ≤ off_margin)")
            return Desire(True, 0.0, pkw, exact_kw=pkw, reason=f"keep on (Δ={profit:.2f} €/h)")
        else:
            if profit >= on_margin:
                return Desire(True, 0.0, pkw, exact_kw=pkw, reason=f"profitable (Δ={profit:.2f} €/h ≥ on_margin)")
            return Desire(False, 0.0, 0.0, reason=f"not profitable (Δ={profit:.2f} €/h < on_margin)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Diskret: >=95% der Nennleistung -> ON, sonst OFF.
        Schaltet via action_on_entity/off_entity und schreibt last_flip_ts bei Zustandswechsel.
        """
        # Datensatz suchen
        m = None
        for mx in (list_miners() or []):
            if mx.get("id") == self.miner_id:
                m = mx
                break
        if not m:
            print(f"[miner {self.miner_id}] apply skipped: not found", flush=True)
            return

        # Premium-Gate
        if not is_premium_enabled():
            free_id = _free_miner_id()
            if m.get("id") != free_id:
                print(f"[miner {self.miner_id}] premium required - skipping apply", flush=True)
                return

        pkw = _num(m.get("power_kw"), 0.0)
        on_ent = m.get("action_on_entity", "") or ""
        off_ent = m.get("action_off_entity", "") or ""

        should_on = pkw > 0.0 and alloc_kw >= 0.95 * pkw
        prev_on = bool(m.get("on"))

        try:
            if should_on and not prev_on:
                if on_ent:
                    call_action(on_ent, True)
                update_miner(self.miner_id, on=True, last_flip_ts=time.time())
                print(f"[miner {self.miner_id}] apply ~{alloc_kw:.2f} kW (ON)", flush=True)
            elif (not should_on) and prev_on:
                if off_ent:
                    call_action(off_ent, False)
                update_miner(self.miner_id, on=False, last_flip_ts=time.time())
                print(f"[miner {self.miner_id}] apply 0 kW (OFF)", flush=True)
            else:
                # kein Zustandswechsel
                pass
        except Exception as e:
            print(f"[miner {self.miner_id}] apply error: {e}", flush=True)
