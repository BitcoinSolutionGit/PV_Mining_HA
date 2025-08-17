# services/power_planner.py
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple
from services.consumers.base import Ctx, Desire, BaseConsumer
from services.consumers.registry import get_consumer_for_id

Number = float

def _fmt(x: Optional[Number]) -> str:
    if x is None:
        return "None"
    try:
        return f"{x:.3f}"
    except Exception:
        return str(x)

def plan_and_allocate(
    ctx: Ctx,
    order: List[str],
    consumers: Optional[Dict[str, BaseConsumer]] = None,
    dry_run: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Verteilt Leistung gemäß Priority-Order.
    - PV-Überschuss (ctx.surplus_kw) wird zuerst verwendet.
    - Grid wird nur gezogen, um 'must_run' mindestens min_kw (oder exact_kw) zu sichern.
    - Jeder Consumer liefert via compute_desire(ctx) seinen Wunsch (Desire).

    Rückgabe: Dict mit Rest-PV, zusätzlichem Grid-Draw und pro-Consumer-Allokationen.
    """
    log = logger or (lambda s: None)

    # Consumer-Map aufbauen (falls nicht injiziert)
    cons_map: Dict[str, BaseConsumer] = consumers.copy() if consumers else {}

    def _get_cons(cid: str) -> Optional[BaseConsumer]:
        if cid in cons_map:
            return cons_map[cid]
        c = get_consumer_for_id(cid)
        if c:
            cons_map[cid] = c
        return c

    pv_left: float = max(ctx.surplus_kw, 0.0)
    grid_draw: float = 0.0
    allocations: List[Tuple[str, float, float, Desire]] = []

    log(f"[plan] order={order}")
    log(f"[plan] start surplus={pv_left:.3f} kW")

    for cid in order:
        # „Sinks“ wie grid_feed behandeln wir am Ende nur informativ
        if cid in ("grid_feed", "inflow"):
            log(f"[plan] sink '{cid}' at end; leftover will be fed in.")
            continue

        cons = _get_cons(cid)
        if not cons:
            log(f"[plan] skip unknown consumer id='{cid}'")
            continue

        # Desire vom Consumer
        try:
            desire: Desire = cons.compute_desire(ctx)
        except Exception as e:
            log(f"[plan] error: compute_desire({cid}) -> {e}")
            continue

        wants   = bool(desire.wants)
        min_kw  = max(desire.min_kw or 0.0, 0.0)
        max_kw  = max(desire.max_kw or 0.0, 0.0)
        exact   = desire.exact_kw
        must    = bool(desire.must_run)
        reason  = desire.reason or ""

        # Zielbereich bestimmen
        if exact is not None:
            target_min = max(min_kw, float(exact))
            target_max = float(exact)
        else:
            target_min = min_kw
            target_max = max(min_kw, max_kw)

        if not wants or target_max <= 0.0:
            allocations.append((cid, 0.0, 0.0, desire))
            log(f"[DRY] {cid:12s} wants={wants} min={_fmt(min_kw)} max={_fmt(max_kw)} "
                f"exact={_fmt(exact)} must={must} -> alloc=0.000 (pv=0.000, grid=0.000) | {reason}")
            continue

        # 1) PV zuweisen
        pv_alloc = min(pv_left, target_max)
        # 2) Grid nur für must_run, um min zu erreichen
        need_min = max(target_min - pv_alloc, 0.0)
        grid_alloc = need_min if must and need_min > 0 else 0.0

        alloc_total = pv_alloc + grid_alloc

        # „exakt“ nicht übererfüllen
        if exact is not None:
            alloc_total = min(alloc_total, exact)
            if alloc_total < pv_alloc:
                # Wenn exact kleiner als bereits geplante PV-Zuteilung, PV reduzieren
                pv_alloc = alloc_total
                grid_alloc = 0.0

        # State updaten
        pv_left = max(pv_left - pv_alloc, 0.0)
        grid_draw += grid_alloc

        allocations.append((cid, pv_alloc, grid_alloc, desire))

        # Anwenden (nur wenn nicht dry_run)
        if not dry_run:
            try:
                cons.apply_allocation(ctx, alloc_total)
            except Exception as e:
                log(f"[plan] error: apply_allocation({cid}, {alloc_total:.3f}) -> {e}")

        # Log
        log(f"[DRY] {cid:12s} wants={wants} min={_fmt(min_kw)} max={_fmt(max_kw)} "
            f"exact={_fmt(exact)} must={must} -> alloc={alloc_total:.3f} "
            f"(pv={pv_alloc:.3f}, grid={grid_alloc:.3f}) | {reason}")

    log(f"[plan] end   surplus={pv_left:.3f} kW, grid_draw={grid_draw:.3f} kW")

    return {
        "pv_left": pv_left,
        "grid_draw": grid_draw,
        "allocations": allocations,
    }
