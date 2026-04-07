from __future__ import annotations

import time

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Desire:
    """Wunsch eines Verbrauchers fuer die naechste Planungsrunde."""

    wants: bool
    min_kw: float
    max_kw: float
    must_run: bool = False
    exact_kw: Optional[float] = None
    reason: str = ""


@dataclass
class Ctx:
    """Planungskontext fuer Energiesituation und oekonomische Parameter."""

    ts: float = 0.0
    pv_kw: float = 0.0
    grid_kw: float = 0.0
    feedin_kw: float = 0.0
    grid_price_eur_kwh: float = 0.0
    pv_cost_eur_kwh: float = 0.0
    fee_down_eur_kwh: float = 0.0
    fee_up_eur_kwh: float = 0.0
    btc_price_eur: float = 0.0
    network_hashrate_ths: float = 0.0
    block_reward_btc: float = 3.125
    tax_percent: float = 0.0
    _surplus_kw_override: Optional[float] = None

    @property
    def surplus_kw(self) -> float:
        if self._surplus_kw_override is not None:
            return max(self._surplus_kw_override, 0.0)
        return max(self.feedin_kw, 0.0)

    @surplus_kw.setter
    def surplus_kw(self, value: float) -> None:
        try:
            self._surplus_kw_override = float(value)
        except Exception:
            self._surplus_kw_override = None


def now() -> float:
    return time.time()


class BaseConsumer(ABC):
    """Basisklasse fuer alle Consumer."""

    id: str = "consumer"
    label: str = "Consumer"

    def __init__(self, id: str | None = None, label: str | None = None) -> None:
        if id:
            self.id = id
        if label:
            self.label = label

    @abstractmethod
    def compute_desire(self, ctx: Ctx | None = None) -> Desire:
        raise NotImplementedError

    @abstractmethod
    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r} label={self.label!r}>"


__all__ = ["Desire", "BaseConsumer", "Ctx", "now"]
