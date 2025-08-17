# consumers/cooling.py
from __future__ import annotations
from .base import Desire
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from services.miners_store import list_miners

def desire_now(any_profitable_miner_requires_cooling: bool) -> tuple[Desire, float, bool]:
    """
    Gibt Desire für Cooling zurück sowie (power_kw_cfg, running_now_flag)
    """
    if not bool(set_get("cooling_feature_enabled", False)):
        return Desire(False,0,0,False,None,"feature disabled"), 0.0, False

    c = get_cooling() or {}
    mode = (str(c.get("mode") or "").lower() or "manual")
    on = bool(c.get("on"))
    kw = float(c.get("power_kw") or 0.0)

    running_now = on  # falls du eine ready_entity hast, könntest du das hier genauer prüfen

    if mode == "manual":
        # respektiere manuellen Schalter
        des = Desire(wants=on, min_kw=kw if on else 0.0, max_kw=kw if on else 0.0,
                     must_run=on, exact_kw=(kw if on else 0.0),
                     reason="manual state")
        return des, kw, running_now

    # auto: nur wenn mind. ein profitabler Miner cooling benötigt
    wants = bool(any_profitable_miner_requires_cooling)
    des = Desire(wants=wants, min_kw=0.0, max_kw=(kw if wants else 0.0),
                 must_run=False, exact_kw=(kw if wants else None),
                 reason=("needed by profitable miner" if wants else "no profitable miner needs cooling"))
    return des, kw, running_now

class CoolingConsumer:
    """
    Thin adapter für den Planner/Registry.
    Cooling verlangt selbst keine Leistung; es wird nur gestartet,
    wenn ein profitabler Miner mit Cooling-Pflicht versorgt werden soll.
    """
    def __init__(self) -> None:
        cfg = get_cooling() or {}
        self._label = cfg.get("name", "Cooling circuit")

    @property
    def id(self) -> str:
        return "cooling"

    @property
    def label(self) -> str:
        return self._label

    def desire_now(self) -> Desire:
        enabled = bool(set_get("cooling_feature_enabled", False))
        if not enabled:
            return Desire(False, 0.0, 0.0, False, None, "feature disabled")
        # kein eigener Bedarf – Planner verteilt nur, wenn Miner das erfordern
        return Desire(False, 0.0, 0.0, False, None,
                      "idle (starts only when a miner needs cooling & is profitable)")

    # Platzhalter für später (z.B. call_action etc.)
    def apply(self, kw: float) -> None:  # noqa: ARG002
        return

    from .base import Desire
    from services.settings_store import get_var as set_get
    from services.cooling_store import get_cooling

    class CoolingConsumer:
        def __init__(self) -> None:
            cfg = get_cooling() or {}
            self._label = cfg.get("name", "Cooling circuit")

        @property
        def id(self) -> str:
            return "cooling"

        @property
        def label(self) -> str:
            return self._label

        def desire_now(self) -> Desire:
            enabled = bool(set_get("cooling_feature_enabled", False))
            if not enabled:
                return Desire(False, 0.0, 0.0, False, None, "feature disabled")
            return Desire(False, 0.0, 0.0, False, None,
                          "idle (starts only when a miner needs cooling & is profitable)")

        def apply(self, kw: float) -> None:
            return
