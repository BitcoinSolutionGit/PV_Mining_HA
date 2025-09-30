# services/consumers/cooling.py
from __future__ import annotations

import time
from services.consumers.base import BaseConsumer, Desire, Ctx
from services.cooling_store import get_cooling, set_cooling
from services.settings_store import get_var as set_get
from services.miners_store import list_miners, update_miner
from services.ha_entities import call_action
from services.ha_sensors import get_sensor_value
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.energy_mix import incremental_mix_for
from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour

_last_ui_on_state: "Optional[bool]" = None  # remembers last UI 'on' flag we saw
_last_switch_ts: float | None = None  # <— neu: merkt den letzten tatsächlichen Flip (ON/OFF)
# NEU: Entprell-/Laufzeit-States
_last_cmd: "Optional[str]" = None     # "on" | "off"
_last_cmd_ts: float = 0.0
_last_on_ts: float = 0.0
_last_off_ts: float = 0.0

def _can_send(cmd: str, now: float, cooldown_s: float) -> bool:
    """Unterdrückt gleiche Kommandos innerhalb eines Cooldowns."""
    global _last_cmd, _last_cmd_ts
    if _last_cmd == cmd and (now - _last_cmd_ts) < cooldown_s:
        return False
    _last_cmd, _last_cmd_ts = cmd, now
    return True

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
    """Opportunitätskosten PV gemäß Settings (zero | feedin)."""
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

def _cooling_on_fraction(default: float = 0.50) -> float:
    """Startschwelle für AUTO: Anteil der Nennleistung (0.0–1.0). Werte >1 als Prozent."""
    try:
        x = float(set_get("cooling_on_fraction", default) or default)
        if x > 1.0:
            x = x / 100.0
        return max(0.0, min(1.0, x))
    except Exception:
        return default

def _cooling_min_run_s(default: int = 20) -> int:
    try:
        return int(float(set_get("cooling_min_run_s", default) or default))
    except Exception:
        return default

def _cooling_min_off_s(default: int = 20) -> int:
    try:
        return int(float(set_get("cooling_min_off_s", default) or default))
    except Exception:
        return default

# --- deine CoolingConsumer.compute_desire() ersetzt durch diese Version ---
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

        is_on_desired = _truthy(c.get("on"), False)  # Wunsch (UI/Auto)
        ha_on_val = c.get("ha_on")
        is_running = bool(ha_on_val) if ha_on_val is not None else is_on_desired

        if not enabled:
            return Desire(False, 0.0, 0.0, reason="disabled")
        if power_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no power configured")

        # ---------- MANUAL OVERRIDE ----------
        if mode != "auto":
            if is_on_desired:
                return Desire(True, power_kw, power_kw, must_run=True, exact_kw=power_kw, reason="manual override")
            return Desire(False, 0.0, 0.0, reason="manual mode (off)")

        # ---------- Auto-Logik ----------
        # Wenn schon ein Miner läuft, der Kühlung braucht -> anlassen
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
            # nur wenn Kandidaten existieren (oben bereits geprüft)
            return Desire(True, 0.0, power_kw, exact_kw=power_kw, reason="neg grid price with candidates")

        # Kosten-Parameter
        pv_cost = _pv_cost_per_kwh()

        # BTC-Erträge (einmal berechnen)
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)
        sat_th_h = sats_per_th_per_hour(reward, net_ths) if net_ths > 0 else 0.0
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0

        # Cooling darf starten, wenn es mind. EINEN Kandidaten gibt, für den
        # Miner+Cooling im aktuellen Mix PV-only ODER profitabel (nach Steuer) ist.
        for m in candidates:
            m_kw = _num(m.get("power_kw"), 0.0)
            ths  = _num(m.get("hashrate_ths"), 0.0)

            # ΔP: wenn Cooling noch aus, dann Miner+Cooling; wenn an, nur Miner
            delta = m_kw + (0.0 if is_running else power_kw) # nicht mehr 'is_on'
            if delta <= 0.0:
                continue

            pv_share, grid_share, _ = incremental_mix_for(delta)
            blended = pv_share * pv_cost + grid_share * eff_grid_cost

            # Ertrag/h nach Steuer
            sats_h = sat_th_h * ths
            revenue_eur_h = sats_h * eur_per_sat
            after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

            # Cooling-Anteil fair verteilen (hier: Cooling würde neu starten)
            cool_share = 0.0
            if not is_running and power_kw > 0.0:
                n_future = 1  # nur dieser Miner (keine aktiven Cooling-Miner -> oben hätten wir 'active_need')
                cool_share = (power_kw / max(n_future, 1)) * blended

            miner_cost = m_kw * blended
            total_cost = miner_cost + cool_share

            if grid_share <= 1e-6 or after_tax >= total_cost:
                return Desire(
                    True, 0.0, power_kw, exact_kw=power_kw,
                    reason=("pv_only_ok" if grid_share <= 1e-6 else f"profitable (Δ={after_tax - total_cost:.2f} €/h)")
                )

        return Desire(False, 0.0, 0.0, reason="no qualifying miner (pv/profit)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Cooling via HA-Action.
        - MANUAL: Nur bei *UI-Änderung* schalten; HA-Änderungen werden respektiert.
        - AUTO: Nur bei Zustandswechsel schalten (kein periodisches retriggern).
        - Safety: nur wenn ON angefordert wurde, HA aber explizit OFF meldet.
        """
        global _last_ui_on_state, _last_on_ts, _last_off_ts, _last_switch_ts, _last_ui_on_state

        c = get_cooling() or {}
        power_kw = _num(c.get("power_kw"), 0.0)
        on_ent = (c.get("action_on_entity") or "").strip()
        off_ent = (c.get("action_off_entity") or "").strip()

        mode = str(c.get("mode") or "manual").lower()
        is_manual = (mode != "auto")

        ui_on = _truthy(c.get("on"), False)  # UI-Wunsch (unabhängig von HA)
        ha_raw = c.get("ha_on")  # True/False/None
        running = bool(ha_raw) if ha_raw is not None else ui_on  # Istzustand

        # ---------- MANUAL ----------
        if is_manual:
            try:
                # Falls HA einen Zustand liefert und der weicht vom UI ab:
                if ha_raw is not None and bool(ha_raw) != ui_on:
                    ui_changed = (_last_ui_on_state is None) or (ui_on != _last_ui_on_state)
                    if ui_changed:
                        # Nur wenn der UI-Wunsch *jetzt* geändert wurde, setzen wir HA entsprechend.
                        if ui_on and not bool(ha_raw):
                            if on_ent: call_action(on_ent, True)
                            _last_on_ts = time.time()  # ⬅️ NEU
                            _last_switch_ts = time.time()
                            print("[cooling] MANUAL: UI->ON (apply to HA)", flush=True)
                        elif (not ui_on) and bool(ha_raw):
                            if off_ent: call_action(off_ent, False)
                            _last_off_ts = time.time()  # ⬅️ NEU
                            _last_switch_ts = time.time()
                            print("[cooling] MANUAL: UI->OFF (apply to HA)", flush=True)
                    else:
                        # UI nicht geändert → HA hat wahrscheinlich manuell Vorrang -> nichts tun
                        print("[cooling] MANUAL: HA/UI mismatch but UI unchanged → respecting HA", flush=True)
                else:
                    # HA stimmt mit UI überein *oder* es gibt kein ha_on → ggf. schalten
                    if ha_raw is None:
                        # Kein Ready-Sensor: wir treiben über UI-Wunsch
                        if ui_on and not running:
                            if on_ent: call_action(on_ent, True)
                            _last_on_ts = time.time()  # ⬅️ NEU
                            _last_switch_ts = time.time()
                            print("[cooling] MANUAL: no ha_on, switching ON", flush=True)
                        elif (not ui_on) and running:
                            if off_ent: call_action(off_ent, False)
                            _last_off_ts = time.time()  # ⬅️ NEU
                            _last_switch_ts = time.time()
                            print("[cooling] MANUAL: no ha_on, switching OFF", flush=True)
                    # wenn ha_raw vorhanden und gleich UI → nichts tun
            except Exception as e:
                print(f"[cooling] apply error (manual): {e}", flush=True)
            finally:
                _last_ui_on_state = ui_on
            return

        # ---------- AUTO ----------
        frac = _cooling_on_fraction(default=0.50)
        should_on = power_kw > 0.0 and alloc_kw >= frac * power_kw

        try:
            now_ts = time.time()
            requested_on = should_on and (not running)
            requested_off = (not should_on) and running

            # Debounce / Anti-Flattern:
            if requested_on and (_last_switch_ts is not None) and (now_ts - _last_switch_ts < _cooling_min_off_s()):
                print("[cooling] AUTO debounce: min OFF not elapsed -> suppress ON", flush=True)
                requested_on = False
            if requested_off and (_last_switch_ts is not None) and (now_ts - _last_switch_ts < _cooling_min_run_s()):
                print("[cooling] AUTO debounce: min RUN not elapsed -> suppress OFF", flush=True)
                requested_off = False

            if requested_on:
                if on_ent: call_action(on_ent, True)
                _last_switch_ts = now_ts
                print(f"[cooling] AUTO request ON (~{alloc_kw:.2f} kW, frac={frac:.2f})", flush=True)
            elif requested_off:
                if off_ent: call_action(off_ent, False)
                _last_switch_ts = now_ts
                print(f"[cooling] AUTO request OFF (~{alloc_kw:.2f} kW, frac={frac:.2f})", flush=True)
            else:
                return  # kein Zustandswechsel
            ...
        except Exception as e:
            print(f"[cooling] apply error (auto): {e}", flush=True)




