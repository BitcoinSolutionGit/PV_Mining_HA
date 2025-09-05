# services/consumers/miner.py
from __future__ import annotations

from typing import Optional, List
from services.consumers.base import BaseConsumer, Desire, Ctx
from services.license import is_premium_enabled
from services.miners_store import list_miners, update_miner
from services.settings_store import get_var as set_get
from services.electricity_store import get_var as elec_get
from services.ha_entities import call_action
from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour

def _truthy(x, default=False) -> bool:
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1","true","on","yes","y","auto","enabled"):
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

def _free_miner_id() -> Optional[str]:
    """
    Der 'freie' Miner ist der erste in der Liste (bzw. älteste, falls gewünscht).
    Fallback: None, wenn keine Miner existieren.
    """
    try:
        miners = list_miners() or []
        if not miners:
            return None
        # stabil: erster Eintrag in der YAML-Liste ist "Miner 1"
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
            from services.ha_sensors import get_sensor_value
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
    try:
        from services.cooling_store import get_cooling
        c = get_cooling() or {}
        return _truthy(c.get("on"), False)
    except Exception:
        return False

def _eligible_miners() -> List[dict]:
    free_id = _free_miner_id()
    prem = is_premium_enabled()

    out = []
    for m in (list_miners() or []):
        # ⬇️ Gate: ohne Premium nur der "freie" Miner darf mitspielen
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
        # optional: Namen aus Store
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
        # Miner-Datensatz suchen
        m = None
        for mx in (list_miners() or []):
            if mx.get("id") == self.miner_id:
                m = mx
                break
        if not m:
            return Desire(False, 0.0, 0.0, reason="not found")

        # ⬇️ Gate: ohne Premium nur der freie Miner liefert Desire
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

        # BTC-Erlöse
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

        sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
        sats_per_h = sat_th_h * ths
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
        revenue_eur_h = sats_per_h * eur_per_sat
        after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct/100.0, 1.0)))

        # Kosten: PV-Opportunität
        pv_cost = _pv_cost_per_kwh()

        # Cooling-Anteil (falls gebraucht) – nur wenn Cooling noch nicht läuft
        cooling_kw = _cooling_power_kw() if _cooling_required(m) else 0.0
        cool_share = 0.0
        if cooling_kw > 0.0 and not _cooling_running_now():
            active = [mx for mx in _eligible_miners() if _truthy(mx.get("on"), False) and _cooling_required(mx)]
            n_future = len(active) + 1
            cool_share = (cooling_kw * pv_cost) / max(n_future, 1)

        total_cost_h = pkw * pv_cost + cool_share
        profit = after_tax - total_cost_h

        if profit > 0.0:
            # Diskret: volle Leistung gewünscht
            return Desire(
                wants=True,
                min_kw=0.0,
                max_kw=pkw,
                must_run=False,
                exact_kw=pkw,
                reason=f"profitable (Δ={profit:.2f} €/h)",
            )
        else:
            return Desire(False, 0.0, 0.0, reason=f"not profitable (Δ={profit:.2f} €/h)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Miner ist diskret: >=95% der Nennleistung -> ON, sonst OFF.
        Schaltet per action_on_entity/off_entity (falls konfiguriert) und spiegelt 'on' im Store.
        """
        # Miner-Datensatz suchen
        m = None
        for mx in (list_miners() or []):
            if mx.get("id") == self.miner_id:
                m = mx
                break
        if not m:
            print(f"[miner {self.miner_id}] apply skipped: not found", flush=True)
            return

        # ⬇️ Gate: ohne Premium keine Schalthandlungen für Miner > 1
        if not is_premium_enabled():
            free_id = _free_miner_id()
            if m.get("id") != free_id:
                print(f"[miner {self.miner_id}] premium required - skipping apply", flush=True)
                return

        pkw = _num(m.get("power_kw"), 0.0)
        on_ent  = m.get("action_on_entity", "") or ""
        off_ent = m.get("action_off_entity", "") or ""

        should_on = pkw > 0.0 and alloc_kw >= 0.95 * pkw
        try:
            if should_on:
                if on_ent:
                    call_action(on_ent, True)
                update_miner(self.miner_id, on=True)
                print(f"[miner {self.miner_id}] apply ~{alloc_kw:.2f} kW (ON)", flush=True)
            else:
                if off_ent:
                    call_action(off_ent, False)
                update_miner(self.miner_id, on=False)
                print(f"[miner {self.miner_id}] apply 0 kW (OFF)", flush=True)
        except Exception as e:
            print(f"[miner {self.miner_id}] apply error: {e}", flush=True)
