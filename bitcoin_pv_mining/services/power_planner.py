# services/power_planner.py
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from services.consumers.base import Ctx, Desire, BaseConsumer, now
from services.consumers.registry import get_consumer_for_id

# --- Surplus helpers (liest deine Sensor-Mappings aus /config) ---
import os
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value

# --- stdout logger helper (Add-on-Log) ---
def _stdout_logger(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass

Number = float

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _map(key: str) -> str:
    def _mget(path, k):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(k) or "").strip()
    return _mget(SENS_OVR, key) or _mget(SENS_DEF, key)


def _kw(val: float) -> float:
    """Heuristik: falls der Sensor in W liefert, nach kW umrechnen."""
    try:
        v = float(val)
    except Exception:
        return 0.0
    return v / 1000.0 if abs(v) > 2000 else v


def read_surplus_kw() -> float:
    """Aktueller Überschuss in kW (>=0). Nimmt max(Feed-in, PV-Prod - Grid-Import)."""
    from services.ha_sensors import get_sensor_value

    def _m(path, k):
        return (load_yaml(path, {}).get("mapping", {}) or {}).get(k, "").strip()

    def _map(key: str) -> str:
        return _m(SENS_OVR, key) or _m(SENS_DEF, key)

    def _f(v, d=0.0):
        try:
            return float(v) if v not in (None, "") else d
        except Exception:
            return d

    def _kw(v: float) -> float:
        try:
            f = float(v)
        except Exception:
            return 0.0
        return f / 1000.0 if abs(f) > 2000 else f

    # A) Feed-in (Export) – negatives Export-Sign korrigieren
    feed_id = _map("grid_feed_in")
    feed_kw = None
    if feed_id:
        val = _kw(_f(get_sensor_value(feed_id), 0.0))
        export_kw = abs(val) if val < 0 else val
        feed_kw = max(export_kw, 0.0)

    # B) PV-Produktion minus Netzbezug
    pv_id  = _map("pv_production")
    imp_id = _map("grid_consumption")
    diff_kw = None
    if pv_id and imp_id:
        pv_kw  = max(_kw(_f(get_sensor_value(pv_id), 0.0)), 0.0)
        imp_kw = max(_kw(_f(get_sensor_value(imp_id), 0.0)), 0.0)
        diff_kw = max(pv_kw - imp_kw, 0.0)

    cands = [x for x in (feed_kw, diff_kw) if x is not None]
    return max(cands + [0.0]) if cands else 0.0




# --- Format-Helfer fürs Log ---
def _fmt(x: Optional[Number]) -> str:
    if x is None:
        return "None"
    try:
        return f"{x:.3f}"
    except Exception:
        return str(x)


# ----------------------------------------------------------------------------------
# Kernfunktion: plant und (optional) setzt um
# ----------------------------------------------------------------------------------
def plan_and_allocate(
    ctx: Ctx,
    order: List[str],
    consumers: Optional[Dict[str, BaseConsumer]] = None,
    *,
    apply: bool = False,               # True = apply_allocation() ausführen
    dry_run: bool = True,              # True = nur rechnen+loggen
    log: bool = True,                  # bequemes Flag für stdout-Logging
    logger: Optional[Callable[[str], None]] = None,  # eigener Logger

) -> dict:
    """
    Verteilt Leistung gemäß Priority-Order.

    Regeln:
      - Es wird der *tatsächliche* PV-Überschuss (read_surplus_kw) verwendet.
        Hauslast ist dabei bereits implizit gedeckt (sobald grid_feed_in verfügbar).
      - PV wird zuerst verteilt. Grid wird nur gezogen, um 'must_run' mindestens
        das 'min_kw' (oder 'exact_kw') zu garantieren.
      - Jeder Consumer liefert via compute_desire(ctx) seinen Wunsch (Desire).

    Rückgabe:
      {
        "pv_left": float,           # unbenutzter PV-Überschuss
        "grid_draw": float,         # zusätzlich benötigter Netzbezug für must_run-Minima
        "allocations": List[Tuple[cid, pv_alloc, grid_alloc, Desire]]
      }
    """
    # Logger wählen: expliziter logger > stdout > no-op
    log_fn = (logger or _stdout_logger) if log else (lambda *_: None)

    # Consumer-Map aufbauen/verwenden
    cons_map: Dict[str, BaseConsumer] = consumers.copy() if consumers else {}

    def _get_cons(cid: str) -> Optional[BaseConsumer]:
        if cid in cons_map:
            return cons_map[cid]
        c = get_consumer_for_id(cid)
        if c:
            cons_map[cid] = c
        return c

    # PV-Überschuss (Hauslast-bereinigt) ermitteln
    surplus_kw = read_surplus_kw()
    pv_left: float = max(surplus_kw, 0.0)
    grid_draw: float = 0.0
    allocations: List[Tuple[str, float, float, Desire]] = []

    log_fn(f"[plan] order={order}")
    log_fn(f"[plan] start surplus={pv_left:.3f} kW")

    # Surplus-Debug: Rohwerte der Sensoren anzeigen
    try:
        from services.ha_sensors import get_sensor_value
        def _f(v, d=0.0):
            try:
                return float(v) if v not in (None, "") else d
            except Exception:
                return d

        def _kw(v):
            try:
                f = float(v)
            except Exception:
                return 0.0
            return f / 1000.0 if abs(f) > 2000 else f

        _feed_id = _map("grid_feed_in")
        _pv_id = _map("pv_production")
        _imp_id = _map("grid_consumption")

        _feed_v = _kw(_f(get_sensor_value(_feed_id), 0.0)) if _feed_id else None
        _pv_v = _kw(_f(get_sensor_value(_pv_id), 0.0)) if _pv_id else None
        _imp_v = _kw(_f(get_sensor_value(_imp_id), 0.0)) if _imp_id else None

        log_fn(f"[plan:surplus_dbg] feed={_feed_id}:{_feed_v}  pv={_pv_id}:{_pv_v}  imp={_imp_id}:{_imp_v}")
    except Exception as _e:
        log_fn(f"[plan:surplus_dbg] failed: {_e}")

    # DEBUG: Sensor-Rohwerte für Surplus nachvollziehen
    try:
        _feed_id = _map("grid_feed_in")
        _pv_id = _map("pv_production")
        _imp_id = _map("grid_consumption")
        _feed_v = _kw(_f(get_sensor_value(_feed_id), 0.0)) if _feed_id else None
        _pv_v = _kw(_f(get_sensor_value(_pv_id), 0.0)) if _pv_id else None
        _imp_v = _kw(_f(get_sensor_value(_imp_id), 0.0)) if _imp_id else None
        log_fn(
            f"[plan:surplus_dbg] feed_id={_feed_id} val={_feed_v}  pv_id={_pv_id} val={_pv_v}  imp_id={_imp_id} val={_imp_v}")
    except Exception as _e:
        log_fn(f"[plan:surplus_dbg] failed: {_e}")

    # Durch die priorisierten Verbraucher laufen
    for cid in order:
        # „Sinks“ nur informativ: leftover PV wird eingespeist
        if cid in ("grid_feed", "inflow"):
            log_fn(f"[plan] sink '{cid}' at end; leftover will be fed in.")
            continue

        cons = _get_cons(cid)
        if not cons:
            log_fn(f"[plan] skip unknown consumer id='{cid}'")
            continue

        # Desire abfragen
        try:
            desire: Desire = cons.compute_desire(ctx)

            log_fn(f"[plan:desire] {cid}: wants={desire.wants} min={desire.min_kw:.2f} "
                   f"max={desire.max_kw:.2f} must={getattr(desire, 'must_run', False)} "
                   f"reason={getattr(desire, 'reason', '')}")

        except Exception as e:
            log_fn(f"[plan] error: compute_desire({cid}) -> {e}")
            continue

        wants = bool(desire.wants)
        min_kw = max(desire.min_kw or 0.0, 0.0)
        max_kw = max(desire.max_kw or 0.0, 0.0)
        exact = desire.exact_kw
        must = bool(desire.must_run)
        reason = desire.reason or ""

        # Zielbereich bestimmen
        if exact is not None:
            # exact kann min überstimmen (min als Untergrenze absichern)
            target_min = max(min_kw, float(exact))
            target_max = float(exact)
        else:
            target_min = min_kw
            target_max = max(min_kw, max_kw)

        if not wants or target_max <= 0.0:
            log_fn(
                f"[plan:alloc]  {cid}: pv={pv_alloc:.2f} grid={grid_alloc:.2f} total={alloc_total:.2f} pv_left={pv_left:.2f}")
            allocations.append((cid, 0.0, 0.0, desire))
            continue

        log_fn(
            f"[plan:alloc]  {cid}: pv={pv_alloc:.2f} grid={grid_alloc:.2f} "
            f"total={alloc_total:.2f} pv_left={pv_left:.2f}"
        )

        # 1) PV zuweisen bis target_max
        pv_alloc = min(pv_left, target_max)

        # 2) Grid nur, falls must_run und min sonst nicht erfüllt
        need_min = max(target_min - pv_alloc, 0.0)
        grid_alloc = need_min if (must and need_min > 0) else 0.0

        alloc_total = pv_alloc + grid_alloc

        # exact nicht übererfüllen
        if exact is not None:
            alloc_total = min(alloc_total, exact)
            if alloc_total < pv_alloc:
                pv_alloc = alloc_total
                grid_alloc = 0.0

        # State updaten
        pv_left = max(pv_left - pv_alloc, 0.0)
        grid_draw += grid_alloc
        allocations.append((cid, pv_alloc, grid_alloc, desire))

        # Anwenden (nur wenn gewünscht)
        do_apply = bool(apply) and not bool(dry_run)
        if do_apply:
            try:
                cons.apply_allocation(ctx, alloc_total)
            except Exception as e:
                log_fn(f"[plan] error: apply_allocation({cid}, {alloc_total:.3f}) -> {e}")

        # Log
        log_fn(
            f"[DRY] {cid:12s} wants={wants} min={_fmt(min_kw)} max={_fmt(max_kw)} "
            f"exact={_fmt(exact)} must={must} -> alloc={alloc_total:.3f} "
            f"(pv={pv_alloc:.3f}, grid={grid_alloc:.3f}) | {reason}"
        )

    log_fn(f"[plan] end   surplus={pv_left:.3f} kW, grid_draw={grid_draw:.3f} kW")

    return {
        "pv_left": pv_left,
        "grid_draw": grid_draw,
        "allocations": allocations,
    }


# ----------------------------------------------------------------------------------
# Komfort-Wrapper: baut ctx & order automatisch (praktisch für Tests / _engine_tick)
# ----------------------------------------------------------------------------------
def _discover_priority_order() -> List[str]:
    """
    Versucht, die Prioritätenliste aus ui_pages.settings zu lesen.
    Fällt andernfalls auf eine sichere Default-Reihenfolge zurück.
    """
    try:
        from ui_pages.settings import (  # type: ignore
            _prio_available_items as prio_available_items,
            _load_prio_ids as prio_load_ids,
            _prio_merge_with_stored as prio_merge,
        )
        available = prio_available_items()
        stored = prio_load_ids()
        order = prio_merge(stored, available)
        # Sinks nicht ganz vorne – Sicherheitshalber
        if "grid_feed" in order:
            order = [x for x in order if x != "grid_feed"] + ["grid_feed"]
        return order
    except Exception:
        # Minimal sinnvoller Fallback
        return ["house", "battery", "heater", "wallbox", "cooling", "grid_feed"]


def plan_and_allocate_auto(
    *,
    apply: bool = False,
    dry_run: bool = True,
    log: bool = True,
    logger: Optional[Callable[[str], None]] = None,
    consumers: Optional[Dict[str, BaseConsumer]] = None,
    order: Optional[List[str]] = None,
) -> dict:
    """
    Bequemer Auto-Planer:
      - baut einen frischen Kontext (Zeitstempel etc.)
      - ermittelt die aktuelle Priority-Order (Settings) oder nutzt den übergebenen `order`
      - ruft `plan_and_allocate()` mit denselben Flags auf
    """
    ctx = Ctx(ts=now())  # minimaler, gültiger Kontext
    order_eff = order or _discover_priority_order()
    return plan_and_allocate(
        ctx=ctx,
        order=order_eff,
        consumers=consumers,
        apply=apply,
        dry_run=dry_run,
        log=log,
        logger=logger,
    )
