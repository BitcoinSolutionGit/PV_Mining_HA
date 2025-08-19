# services/consumers/cooling.py
from __future__ import annotations

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from services.miners_store import list_miners
from services.ha_entities import call_action

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

        if not enabled:
            return Desire(False, 0.0, 0.0, reason="disabled")
        if mode != "auto":
            return Desire(False, 0.0, 0.0, reason="manual mode")
        if power_kw <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no power configured")

        if not _any_miner_requires_cooling():
            return Desire(False, 0.0, 0.0, reason="no miner requires cooling")

        if not _any_auto_enabled_miner_profitable():
            return Desire(False, 0.0, 0.0, reason="no eligible miner")

        # diskret (an/aus) → exact = power_kw
        return Desire(
            wants=True,
            min_kw=0.0,
            max_kw=power_kw,
            must_run=False,
            exact_kw=power_kw,
            reason="cooling required for auto miners",
        )

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """
        Schaltet Cooling via HA-Action an/aus.
        Schwelle: >= 50% der konfigurierten Leistung -> ON, sonst OFF.
        """
        c = get_cooling() or {}
        power_kw = _num(c.get("power_kw"), 0.0)
        on_ent = c.get("action_on_entity", "") or ""
        off_ent = c.get("action_off_entity", "") or ""

        should_on = power_kw > 0.0 and alloc_kw >= 0.5 * power_kw
        try:
            if should_on:
                if on_ent:
                    call_action(on_ent, True)
                print(f"[cooling] apply ~{alloc_kw:.2f} kW (ON)", flush=True)
            else:
                if off_ent:
                    call_action(off_ent, False)
                print(f"[cooling] apply 0 kW (OFF)", flush=True)
        except Exception as e:
            print(f"[cooling] apply error: {e}", flush=True)
