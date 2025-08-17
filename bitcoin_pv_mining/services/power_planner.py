# services/power_planner.py
"""
Priority-based power planner.

- Liest die priorisierte Verbraucherliste aus den Settings
- Fragt je Consumer Desire (wants/min/max/must_run/exact)
- Verteilt PV-Überschuss streng nach Reihenfolge
- Optional: Must-Run darf Rest aus dem Netz ziehen
- Kann die Zuweisung als Dry-Run nur loggen oder "apply"en
"""

from typing import Any, Dict, List, Optional, Tuple
import os
from dataclasses import asdict

from services.settings_store import get_var as set_get
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.consumers.base import Desire
from services.consumers.registry import get_consumer_for_id

# --- Sensor-Mapping (wie in miners.py) ---
CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")


def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _map(key: str) -> str:
    def _mget(path: str, k: str) -> str:
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(k) or "").strip()
    return _mget(SENS_OVR, key) or _mget(SENS_DEF, key)


def _current_feed_in_kw() -> float:
    feed_id = _map("grid_feed_in")
    val = get_sensor_value(feed_id) if feed_id else 0.0
    return max(_num(val, 0.0), 0.0)  # nur positiver Überschuss


# --- Prioritäten laden (unabhängig von UI) ---
def _load_priority_ids() -> List[str]:
    """
    Erwartete IDs:
      - "house", "battery", "heater", "cooling", "wallbox"
      - "miner:<miner_id>"
      - "grid_feed" (wird als Senke behandelt und bleibt immer am Ende)
    """
    raw = set_get("priority_order", None)
    if isinstance(raw, list) and raw:
        order = list(raw)
    else:
        import json
        raw_json = set_get("priority_order_json", "")
        order = []
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                val = json.loads(raw_json)
                if isinstance(val, list) and val:
                    order = list(val)
            except Exception:
                pass

    # Fallback-Reihenfolge, falls nichts gespeichert:
    if not order:
        order = ["house", "battery", "heater", "cooling", "wallbox", "grid_feed"]

    # Sicherheit: grid_feed ans Ende
    if "grid_feed" in order:
        order = [x for x in order if x != "grid_feed"] + ["grid_feed"]
    return order


# --- Planung / Allokation ---
def _allocate_for_desire(
    desire: Desire,
    available_surplus_kw: float
) -> Tuple[float, float, float]:
    """
    Liefert (alloc_total_kw, from_surplus_kw, from_grid_kw).
    Regelwerk:
      - exact_kw: genau diese Leistung; so viel wie möglich aus PV,
                  Rest (falls must_run) aus dem Netz.
      - must_run: wenn min_kw > verfügbarer PV-Überschuss,
                  Rest aus dem Netz bis min_kw; optional bis max_kw nur aus PV.
      - optional (nicht must_run):
          * nur anfangen, wenn mindestens min_kw aus PV-Überschuss verfügbar
          * dann bis max_kw, aber ausschließlich aus PV
    """
    avail = max(0.0, available_surplus_kw)

    # 1) exact
    if desire.exact_kw is not None:
        exact = max(0.0, float(desire.exact_kw))
        from_surplus = min(exact, avail)
        from_grid = max(0.0, exact - from_surplus) if desire.must_run else 0.0
        alloc = from_surplus + from_grid
        return alloc, from_surplus, from_grid

    # 2) must-run variabel
    if desire.must_run:
        # Mindestens min_kw insgesamt, ggf. Netzanteil
        min_need = max(0.0, desire.min_kw)
        max_need = max(min_need, desire.max_kw)

        # Erst PV
        from_surplus = min(max_need, avail)
        # Falls PV < min_need -> Netz rauf bis min_need
        if from_surplus < min_need:
            from_grid = (min_need - from_surplus)
            alloc = from_surplus + from_grid
            return alloc, from_surplus, from_grid
        else:
            # Schon >= min_need aus PV, optional bis max aus PV
            alloc = from_surplus
            return alloc, from_surplus, 0.0

    # 3) optional
    if not desire.wants:
        return 0.0, 0.0, 0.0

    # Nur starten, wenn min_kw rein aus PV geht
    if avail < max(0.0, desire.min_kw):
        return 0.0, 0.0, 0.0

    target = max(0.0, desire.max_kw)
    from_surplus = min(target, avail)
    alloc = from_surplus  # kein Netzbezug bei optional
    return alloc, from_surplus, 0.0


def plan_and_allocate(apply: bool = False, log: bool = True) -> Dict[str, Any]:
    """
    Kernfunktion: Erzeugt einen Plan entlang der Prioritäten
    und setzt ihn (falls apply=True) um.

    Returns:
      {
        "surplus_start": float,
        "grid_draw_start": float,
        "entries": [
           {
             "id": str,
             "desire": Desire-as-dict,
             "alloc_kw": float,
             "pv_kw": float,
             "grid_kw": float,
             "reason": str
           }, ...
        ],
        "surplus_end": float,
        "grid_draw_end": float
      }
    """
    order = _load_priority_ids()
    surplus = _current_feed_in_kw()
    grid_draw = 0.0

    if log:
        print(f"[plan] order={order}", flush=True)
        print(f"[plan] start surplus={surplus:.3f} kW", flush=True)

    entries: List[Dict[str, Any]] = []

    for pid in order:
        if pid == "grid_feed":
            # „Rest“ bleibt einfach übrig – keine aktive Aktion
            if log:
                print(f"[plan] sink 'grid_feed' at end; leftover will be fed in.", flush=True)
            continue

        cons = get_consumer_for_id(pid)
        if cons is None:
            if log:
                print(f"[plan] skip unknown consumer id={pid!r}", flush=True)
            continue

        # Desire erfragen
        try:
            desire: Desire = cons.compute_desire(None)  # ctx reserviert für später
        except Exception as e:
            if log:
                print(f"[plan] error computing desire for {pid}: {e}", flush=True)
            continue

        alloc, from_pv, from_grid = _allocate_for_desire(desire, surplus)

        # Budget aktualisieren
        surplus = max(0.0, surplus - from_pv)
        grid_draw += max(0.0, from_grid)

        entry = {
            "id": pid,
            "desire": asdict(desire),
            "alloc_kw": alloc,
            "pv_kw": from_pv,
            "grid_kw": from_grid,
            "reason": desire.reason or "",
        }
        entries.append(entry)

        if log:
            flag = "APPLY" if apply else "DRY"
            print(
                f"[{flag}] {pid:12s} wants={desire.wants} "
                f"min={desire.min_kw:.3f} max={desire.max_kw:.3f} "
                f"exact={desire.exact_kw} must={desire.must_run} "
                f"-> alloc={alloc:.3f} (pv={from_pv:.3f}, grid={from_grid:.3f}) "
                f"| {desire.reason}",
                flush=True
            )

        # Anwendung auf den Consumer
        if apply:
            try:
                cons.apply_allocation(None, alloc)  # ctx reserviert für später
            except Exception as e:
                if log:
                    print(f"[apply] error for {pid}: {e}", flush=True)

    result = {
        "surplus_start": _current_feed_in_kw(),  # Info: aktueller Messwert (kann sich leicht geändert haben)
        "grid_draw_start": 0.0,
        "entries": entries,
        "surplus_end": surplus,
        "grid_draw_end": grid_draw,
    }

    if log:
        print(f"[plan] end   surplus={surplus:.3f} kW, grid_draw={grid_draw:.3f} kW", flush=True)

    return result


def dry_run() -> Dict[str, Any]:
    """Bequemer Alias für ein Log ohne Apply."""
    return plan_and_allocate(apply=False, log=True)
