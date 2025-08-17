from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict, Protocol, Any, Dict, List
import time

# Gemeinsamer Kontext, den der Orchestrator an alle Verbraucher gibt
class Ctx(TypedDict, total=False):
    price: float
    fee_down: float
    pv_kw: float
    grid_kw: float
    feed_in_kw: float
    now: float
    cooling: Dict[str, Any]

@dataclass(slots=True)
class Desire:
    """Wunsch/Zuteilung eines Verbrauchers im aktuellen Tick."""
    wants: bool
    min_kw: float
    max_kw: float
    must_run: bool = False
    exact_kw: Optional[float] = None
    reason: str = ""

class Consumer(Protocol):
    """Gemeinsame API für alle Verbraucher."""
    id: str
    label: str

    def compute_desire(self, ctx: Ctx) -> Desire: ...
    def apply(self, allocated_kw: float, ctx: Ctx) -> None: ...
    # Optional: persistente Settings laden/speichern, falls benötigt

def now() -> float:
    return time.time()
