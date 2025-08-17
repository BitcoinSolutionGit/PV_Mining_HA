# services/consumers/base.py
from __future__ import annotations

import time
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class Desire:
    """Wunsch eines Verbrauchers für die nächste Planungsrunde."""
    wants: bool
    min_kw: float
    max_kw: float
    must_run: bool = False
    exact_kw: float | None = None
    reason: str = ""

@dataclass
class Ctx:
    """Planungskontext (aktuelle Energiesituation & ökonomische Parameter)."""
    ts: float = 0.0                       # Zeitstempel (epoch seconds)
    pv_kw: float = 0.0                    # aktuelle PV-Leistung (+)
    grid_kw: float = 0.0                  # Netzbezug (+)
    feedin_kw: float = 0.0                # Netzeinspeisung (+)
    grid_price_eur_kwh: float = 0.0       # Basistarif €/kWh (ohne fee_down)
    pv_cost_eur_kwh: float = 0.0          # Opportunitätskosten PV (0 oder Einspeisetarif - fee_up)
    fee_down_eur_kwh: float = 0.0         # Netzentgelt Bezug
    fee_up_eur_kwh: float = 0.0           # Netzentgelt Einspeisung
    btc_price_eur: float = 0.0
    network_hashrate_ths: float = 0.0
    block_reward_btc: float = 3.125
    tax_percent: float = 0.0

    @property
    def surplus_kw(self) -> float:
        """Momentaner PV-Überschuss (≥0), heuristisch aus feed-in."""
        return max(self.feedin_kw, 0.0)

def now() -> float:
    return time.time()

class BaseConsumer(ABC):
    """Basisklasse für alle Consumer."""
    id: str = "consumer"
    label: str = "Consumer"

    def __init__(self, id: str | None = None, label: str | None = None) -> None:
        if id: self.id = id
        if label: self.label = label

    @abstractmethod
    def compute_desire(self, ctx: Ctx | None = None) -> Desire:
        """Gibt den aktuellen Leistungswunsch zurück."""
        raise NotImplementedError

    @abstractmethod
    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        """Wendet die zugeteilte Leistung an (Schalten, Sollwerte etc.)."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r} label={self.label!r}>"

__all__ = ["Desire", "BaseConsumer", "Ctx", "now"]
