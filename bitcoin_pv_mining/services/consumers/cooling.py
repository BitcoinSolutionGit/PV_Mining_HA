# services/consumers/cooling.py
from __future__ import annotations

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.cooling_store import get_cooling, set_cooling
from services.settings_store import get_var as set_get
from services.miners_store import list_miners
from services.ha_entities import call_action
from services.ha_sensors import get_sensor_value
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.energy_mix import incremental_mix_for
from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour


def _is_auto(m) -> bool:
    return str(m.get("mode") or "manual").lower() == "auto"

def _requires_cooling(m) -> bool:
    flags = [
        m.get("require_cooling"),
        m.get("cooling_required"),
        m.get("needs_cooling"),
        (m.get("cooling") or {}).get("required") if isinstance(m.get("cooling"), dict) else None,
    ]
    return any(_truthy(f) for f in flags)


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

def _any_miner_requires_cooling() -> bool:
    """True, wenn irgendein Miner Cooling braucht (Feld tolerant)."""
    try:
        for m in (list_miners() or []):
            flags = [
                m.get("require_cooling"),
                m.get("cooling_required"),
                m.get("needs_cooling"),
                (m.get("cooling") or {}).get("required") if isinstance(m.get("cooling"), dict) else None,
            ]
            if any(_truthy(f) for f in flags):
                return True
    except Exception:
        pass
    return False

def _any_auto_enabled_miner_profitable() -> bool:
    """
    Grobe Positivprüfung: es gibt mindestens einen Miner in Auto mit sinnvoller
    Konfig (Hashrate/Power > 0). Die genaue Profitprüfung macht der MinerConsumer.
    """
    try:
        for m in (list_miners() or []):
            if not _truthy(m.get("enabled"), False):
                continue
            mode = str(m.get("mode") or "manual").lower()
            if mode != "auto":
                continue
            if _num(m.get("power_kw"), 0.0) <= 0.0:
                continue
            if _num(m.get("hashrate_ths"), 0.0) <= 0.0:
                continue
            return True
    except Exception:
        pass
    return False

def _pv_cost_per_kwh() -> float:
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0
    mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    if mode == "sensor":
        sens = set_get("feedin_price_sensor", "") or ""
        val = _num(get_sensor_value(sens), 0.0) if sens else 0.0
    else:
        val = _num(set_get("feedin_price_value", 0.0), 0.0)
    return max(0.0, val - fee_up)

class CoolingConsumer(BaseConsumer):
    id = "cooling"
    label = "Cooling circuit"

    def compute_desire(self, ctx: Ctx) -> Desire:
        # globales Feature
        feature = bool(set_get("cooling_feature_enabled", False))
        if not feature:
            return Desire(False, 0.0, 0.0, reason="feature disabled")

        c = get_cooling() or {}
        enabled = _truthy(c.get("enabled"), True)
        mode = str(c.get("mode") or "manual").lower()
        power_kw = _num(c.get("power_kw"), 0.0)
        is_on = bool(c.get("on"))

        if not enabled:
            return Desire(False, 0.0, 0.0, reason="disabled")
        if mode != "auto":
            return Desire(False, 0.0, 0.0, reason="manual mode")
        if power_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no power configured")

        # Falls bereits ein Miner läuft, der Kühlung braucht -> anlassen
        try:
            active_need = any(
                _truthy(m.get("on"), False) and _truthy(m.get("require_cooling"), False)
                for m in (list_miners() or [])
            )
        except Exception:
            active_need = False
        if active_need:
            return Desire(True, 0.0, power_kw, exact_kw=power_kw, reason="serve active cooling miners")

        # Kandidaten: auto+enabled Miner, die Cooling brauchen & sinnvolle Leistung haben
        try:
            candidates = [
                m for m in (list_miners() or [])
                if _truthy(m.get("enabled"), False)
                   and str(m.get("mode") or "manual").lower() == "auto"
                   and _truthy(m.get("require_cooling"), False)
                   and _num(m.get("power_kw"), 0.0) > 0.0
                   and _num(m.get("hashrate_ths"), 0.0) > 0.0
            ]
        except Exception:
            candidates = []
        if not candidates:
            return Desire(False, 0.0, 0.0, reason="no miner requires cooling")

        # Netzpreis
        eff_grid_cost = _num(elec_price(), 0.0) + _num(elec_get("network_fee_down_value", 0.0), 0.0)
        if eff_grid_cost <= 0.0:
            return Desire(True, 0.0, power_kw, exact_kw=power_kw, reason="neg grid price")

        # Kosten-Parameter
        pv_cost = _pv_cost_per_kwh()

        # BTC-Erträge (einmal berechnen)
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)
        sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0

        # Gate: Cooling startet, wenn es mind. EINEN Kandidaten gibt, für den
        # Miner+Cooling im aktuellen Mix PV-only ODER profitabel (nach Steuer) ist.
        for m in candidates:
            m_kw = _num(m.get("power_kw"), 0.0)
            ths = _num(m.get("hashrate_ths"), 0.0)

            # ΔP: wenn Cooling noch aus, dann Miner+Cooling; wenn an, dann nur Miner
            delta = m_kw + (0.0 if is_on else power_kw)
            if delta <= 0.0:
                continue

            pv_share, grid_share, _ = incremental_mix_for(delta)
            blended = pv_share * pv_cost + grid_share * eff_grid_cost

            # Ertrag/h nach Steuer
            sats_h = sat_th_h * ths
            revenue_eur_h = sats_h * eur_per_sat
            after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

            # Cooling-Anteil fair verteilen (angenommene Anzahl aktiver Cooling-Miner + dieser)
            cool_share = 0.0
            if not is_on and power_kw > 0.0:
                # aktuell keine aktiven Cooling-Miner (sonst wären wir oben „active_need“)
                n_future = 1  # nur dieser Miner
                cool_share = (power_kw / max(n_future, 1)) * blended

            miner_cost = m_kw * blended
            total_cost = miner_cost + cool_share

            if grid_share <= 1e-6 or after_tax >= total_cost:
                # PV-only ODER profitabel mit Grid -> Cooling darf starten
                return Desire(True, 0.0, power_kw, exact_kw=power_kw,
                              reason=(
                                  "pv_only_ok" if grid_share <= 1e-6 else f"profitable (Δ={after_tax - total_cost:.2f} €/h)"))

        # kein qualifizierender Miner -> Cooling nicht alleine starten
        return Desire(False, 0.0, 0.0, reason="no qualifying miner (pv/profit)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Schaltet Cooling via HA-Action an/aus. Wir setzen 'on' NICHT selbst,
        sondern vertrauen ausschließlich auf HA (ready_entity).
        Zusätzlich: Safety-Off – sind Cooling-Miner an, HA meldet aber 'off',
        schalten wir die Miner sofort ab.
        """
        c = get_cooling() or {}
        power_kw = _num(c.get("power_kw"), 0.0)
        on_ent = c.get("action_on_entity", "") or ""
        off_ent = c.get("action_off_entity", "") or ""
        is_on = bool(c.get("on"))  # ← kommt jetzt direkt aus HA ready_entity

        # Schwelle: >= 50% der konfigurierten Leistung -> ON-Wunsch
        should_on = power_kw > 0.0 and alloc_kw >= 0.5 * power_kw

        try:
            if should_on:
                # Wunsch: AN – wir triggern HA, aber setzen 'on' NICHT selbst
                if on_ent:
                    call_action(on_ent, True)
                print(f"[cooling] apply request ~{alloc_kw:.2f} kW (ASK ON)", flush=True)
            else:
                # Wunsch: AUS
                if off_ent:
                    call_action(off_ent, False)
                print(f"[cooling] apply request 0 kW (ASK OFF)", flush=True)

            # Safety: direkt nach dem Schalten Zustand aus HA prüfen
            c2 = get_cooling() or {}
            ha_on = bool(c2.get("on"))

            if not ha_on:
                # HA meldet 'off' → alle aktiven Miner mit Cooling-Pflicht sofort ausschalten
                try:
                    for m in (list_miners() or []):
                        if _truthy(m.get("on"), False) and _truthy(m.get("require_cooling"), False):
                            off_m = (m.get("action_off_entity") or "").strip()
                            if off_m:
                                call_action(off_m, False)
                            update_miner(m.get("id"), on=False)
                            print(f"[cooling] safety: turned OFF miner {m.get('name') or m.get('id')}", flush=True)
                except Exception as e:
                    print(f"[cooling] safety off miners error: {e}", flush=True)

        except Exception as e:
            print(f"[cooling] apply error: {e}", flush=True)

