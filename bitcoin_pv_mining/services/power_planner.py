# services/power_planner.py
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from services.consumers.base import Ctx, Desire, BaseConsumer, now
from services.consumers.registry import get_consumer_for_id
from services.battery_store import get_var as bat_get

import os
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.settings_store import get_var as set_get
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.energy_mix import surplus_strict_kw as _surplus_strict_kw, incremental_mix_for
from services.export_cap_boost import try_export_cap_boost

# stdout logger -> Add-on-Log
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

def _truthy(x, default=False) -> bool:
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1", "true", "on", "yes", "y", "auto", "enabled"):
        return True
    try:
        return float(s) > 0.0
    except Exception:
        return False


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

# --- Format-Helfer fürs Log (fehlte -> NameError) ---
def _fmt(x: Optional[Number]) -> str:
    if x is None:
        return "None"
    try:
        return f"{float(x):.3f}"
    except Exception:
        return str(x)

def _read_opt_kw(map_key: str) -> Optional[float]:
    sid = _map(map_key)
    if not sid:
        return None
    try:
        val = _kw(_f(get_sensor_value(sid), 0.0))
        return float(val)
    except Exception:
        return None

def _battery_power_kw_from_config() -> Optional[float]:
    """
    Liefert Batterie-Leistung in kW:
      >0 = ENTLAEDUNG (liefert Energie ins Haus)
      <0 = LADUNG     (verbraucht Energie)
    """
    try:
        v_ent = (bat_get("voltage_entity", "") or "").strip()    # optional
        i_ent = (bat_get("current_entity", "") or "").strip()    # optional

        # P aus V * I berechnen
        if v_ent and i_ent:
            v = _f(get_sensor_value(v_ent), None)
            i = _f(get_sensor_value(i_ent), None)
            if v is None or i is None:
                return None
            # ACHTUNG: Dein Kommentar: "+laden / -entladen"
            # bedeutet: i > 0 heißt LADUNG; i < 0 heißt ENTLADUNG.
            # Wir wollen: ENTLADUNG > 0 → deshalb Vorzeichen drehen.
            p_kw = -(v * i) / 1000.0
            return float(p_kw)
    except Exception:
        pass
    return None


def _config_selfcheck(log_fn: Callable[[str], None]) -> None:
    """Loggt, ob die YAMLs vorhanden sind und welche Keys/IDs gefunden werden."""
    try:
        sens_ovr_exists = os.path.exists(SENS_OVR)
        sens_def_exists = os.path.exists(SENS_DEF)
        sens_ovr = load_yaml(SENS_OVR, {}) or {}
        sens_def = load_yaml(SENS_DEF, {}) or {}
        sens_keys_ovr = sorted(list((sens_ovr.get("mapping") or {}).keys()))
        sens_keys_def = sorted(list((sens_def.get("mapping") or {}).keys()))
        log_fn(f"[cfg] sensors.local.yaml exists={sens_ovr_exists} keys={sens_keys_ovr}")
        log_fn(f"[cfg] sensors.yaml       exists={sens_def_exists} keys={sens_keys_def}")

        _feed_id = _map("grid_feed_in")
        _pv_id   = _map("pv_production")
        _imp_id  = _map("grid_consumption")
        log_fn(f"[cfg] resolved: grid_feed_in={_feed_id} pv_production={_pv_id} grid_consumption={_imp_id}")
    except Exception as e:
        log_fn(f"[cfg] sensors selfcheck failed: {e}")

    # Planner-Guard Settings
    try:
        guard_w   = _f(set_get("surplus_guard_w", 100.0), 100.0)
        guard_pct = _f(set_get("surplus_guard_pct", 0.0), 0.0)
        log_fn(f"[cfg] planner guard: surplus_guard_w={guard_w:.0f}W surplus_guard_pct={guard_pct:.3f}")
    except Exception as e:
        log_fn(f"[cfg] planner guard read failed: {e}")


# ---------- Strikter Überschuss: Basislast-Abzug ----------
def _read_pv_import_feed() -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Liest PV, Grid-Import, Feed-in in kW (None wenn nicht gemappt)."""
    pv_id  = _map("pv_production")
    imp_id = _map("grid_consumption")
    feed_id = _map("grid_feed_in")
    pv = _kw(_f(get_sensor_value(pv_id), 0.0)) if pv_id else None
    imp = _kw(_f(get_sensor_value(imp_id), 0.0)) if imp_id else None
    feed = _kw(_f(get_sensor_value(feed_id), 0.0)) if feed_id else None
    # Export positiv
    if feed is not None and feed < 0:
        feed = abs(feed)
    return pv, imp, feed

def _read_energy_flows() -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Liefert: (pv_kw, imp_kw, feed_kw, bat_kw, surplus_direct_kw)
      - bat_kw   >0 = Batterie ENTLAEDT; <0 = LAEDT
      - surplus_direct_kw: direkter Überschuss-Sensor (>=0), falls gemappt (optional)
    """
    pv_id   = _map("pv_production")
    imp_id  = _map("grid_consumption")
    feed_id = _map("grid_feed_in")

    pv   = _kw(_f(get_sensor_value(pv_id), 0.0))   if pv_id   else None
    imp  = _kw(_f(get_sensor_value(imp_id), 0.0))  if imp_id  else None
    feed = _kw(_f(get_sensor_value(feed_id), 0.0)) if feed_id else None
    if feed is not None and feed < 0:
        feed = abs(feed)

    bat  = _battery_power_kw_from_config()         # ← aus battery.yaml
    surplus_direct = _read_opt_kw("pv_surplus")    # ← optionaler Mapping-Key; wenn vorhanden, wird er bevorzugt
    if surplus_direct is not None:
        surplus_direct = max(0.0, surplus_direct)

    return pv, imp, feed, bat, surplus_direct


def _controllable_now_kw() -> float:
    """Schätzt aktuell laufende, von uns kontrollierbare Last (kW)."""
    now_kw = 0.0
    # Heater (aus Prozent × Max-Leistung)
    try:
        from services.heater_store import resolve_entity_id as heat_resolve, get_var as heat_get
        he_id = (heat_resolve("input_heizstab_cache") or "").strip()
        maxp = _f(heat_get("max_power_heater", 0.0), 0.0)  # in kW (oder W, aber UI stellt kW/W sicher)
        if he_id and maxp > 0.0:
            pct = _f(get_sensor_value(he_id), 0.0)
            now_kw += max(0.0, maxp) * max(0.0, min(100.0, pct)) / 100.0
    except Exception:
        pass

    # Cooling (diskret)
    try:
        from services.cooling_store import get_cooling
        c = get_cooling() or {}
        pkw = _f(c.get("power_kw"), 0.0)
        ha_on = c.get("ha_on")
        is_on = (bool(ha_on) if ha_on is not None else _truthy(c.get("on"), False))
        if is_on and pkw > 0.0:
            now_kw += pkw
    except Exception:
        pass

    # Miner (diskret)
    try:
        from services.miners_store import list_miners
        for m in (list_miners() or []):
            if bool(m.get("on")):
                now_kw += _f(m.get("power_kw"), 0.0)
    except Exception:
        pass

    # Wallbox/Battery könntest du später ergänzen
    return max(0.0, now_kw)



# ----------------------------------------------------------------------------------
# Kernfunktion
# ----------------------------------------------------------------------------------
def plan_and_allocate(
    ctx: Ctx,
    order: List[str],
    consumers: Optional[Dict[str, BaseConsumer]] = None,
    *,
    apply: bool = False,
    dry_run: bool = True,
    log: bool = True,
    logger: Optional[Callable[[str], None]] = None,
) -> dict:
    # Logger wählen
    log_fn = (logger or _stdout_logger) if log else (lambda *_: None)

    # Consumer-Map
    cons_map: Dict[str, BaseConsumer] = consumers.copy() if consumers else {}

    def _get_cons(cid: str) -> Optional[BaseConsumer]:
        if cid in cons_map:
            return cons_map[cid]
        c = get_consumer_for_id(cid)
        if c:
            cons_map[cid] = c
        return c

    # Strikter Überschuss + Guard anwenden
    surplus_raw, total_load, ctrl_now, base_load, pv_kw = _surplus_strict_kw()
    guard_w   = _f(set_get("surplus_guard_w", 100.0), 100.0)
    guard_pct = _f(set_get("surplus_guard_pct", 0.0), 0.0)
    guard_kw  = max(guard_w / 1000.0, max(0.0, guard_pct) * surplus_raw)
    surplus_kw = max(surplus_raw - guard_kw, 0.0)

    pv_left: float = surplus_kw
    grid_draw: float = 0.0
    allocations: List[Tuple[str, BaseConsumer, float]] = []

    eff_grid_cost = _f(elec_price(), 0.0) + _f(elec_get("network_fee_down_value", 0.0), 0.0)
    grid_free = (eff_grid_cost <= 0.0)

    # expose planner facts to consumers
    for k, v in (
            ("surplus_kw", pv_left),  # PV-Überschuss nach Guard
            ("grid_cost_eur_kwh", eff_grid_cost),  # effektiver Grid-preis (incl. fee_down)
            ("pv_kw_raw", pv_kw),  # (optional) aktuelle PV-Produktion
            ("surplus_raw_kw", surplus_raw),  # (optional) Überschuss vor Guard
    ):
        # robust für Ctx als Objekt ODER Mapping
        try:
            setattr(ctx, k, v)
        except Exception:
            pass
        try:
            ctx[k] = v
        except Exception:
            pass

    # Ctx anreichern, damit Consumer zugreifen können
    try:
        ctx["surplus_kw"] = pv_left  # strikter PV-Überschuss nach Guard
        ctx["grid_cost_eur_kwh"] = eff_grid_cost
    except Exception:
        pass

    log_fn(f"[plan] grid_cost={eff_grid_cost:.4f} €/kWh -> grid_free={grid_free}")

    log_fn(f"[plan] order={order}")
    log_fn(f"[plan] start surplus={pv_left:.3f} kW")
    log_fn(f"[plan:strict] total={total_load:.3f} kW  ctrl_now={ctrl_now:.3f} kW  base={base_load:.3f} kW  pv={pv_kw:.3f} kW  raw={surplus_raw:.3f} kW")
    log_fn(f"[plan:guard] guard={guard_kw:.3f} kW (w={guard_w:.0f}W, pct={guard_pct:.3f}) -> pv_left={pv_left:.3f} kW")

    # Debug: Rohwerte der Sensoren
    try:
        _feed_id = _map("grid_feed_in")
        _pv_id   = _map("pv_production")
        _imp_id  = _map("grid_consumption")
        _feed_v  = _kw(_f(get_sensor_value(_feed_id), 0.0)) if _feed_id else None
        _pv_v    = _kw(_f(get_sensor_value(_pv_id), 0.0))   if _pv_id   else None
        _imp_v   = _kw(_f(get_sensor_value(_imp_id), 0.0))  if _imp_id  else None
        log_fn(f"[plan:surplus_dbg] feed={_feed_id}:{_feed_v}  pv={_pv_id}:{_pv_v}  imp={_imp_id}:{_imp_v}")
    except Exception as _e:
        log_fn(f"[plan:surplus_dbg] failed: {_e}")

    # --- Export-cap Booster (Try-&-Error) ---
    if apply and not dry_run:
        try:
            feed_kw = max(float(_feed_v or 0.0), 0.0)  # Export (+)
            import_kw = max(float(_imp_v or 0.0), 0.0)  # Import (+)
            try_export_cap_boost(feed_kw=feed_kw, import_kw=import_kw)
        except Exception as e:
            log_fn(f"[cap_boost] error: {e}")

    # Durch die Prioritätsliste
    collected = []  # [(cid, cons, desire)]
    for cid in order:
        if cid in ("grid_feed", "inflow"):
            log_fn(f"[plan] sink '{cid}' at end; leftover will be fed in.")
            continue

        cons = _get_cons(cid)
        if not cons:
            log_fn(f"[plan] skip unknown consumer id='{cid}'")
            continue

        try:
            desire: Desire = cons.compute_desire(ctx)
        except Exception as e:
            log_fn(f"[plan] error: compute_desire({cid}) -> {e}")
            continue

        wants = bool(desire.wants)
        min_kw = max(desire.min_kw or 0.0, 0.0)
        max_kw = max(desire.max_kw or 0.0, 0.0)
        exact = getattr(desire, "exact_kw", None)
        must = bool(getattr(desire, "must_run", False))
        reason = getattr(desire, "reason", "")

        log_fn(f"[plan:desire] {cid}: wants={wants} min={min_kw:.2f} max={max_kw:.2f} must={must} reason={reason}")
        collected.append((cid, cons, desire))

    # Aufteilen
    must_runs = [(cid, cons, de) for (cid, cons, de) in collected if bool(getattr(de, "must_run", False))]
    normals = [(cid, cons, de) for (cid, cons, de) in collected if not bool(getattr(de, "must_run", False))]

    # ---------- 1) MUST-RUNS ZUERST (Grid erlaubt) ----------
    for cid, cons, de in must_runs:
        # geforderte Leistung: exact_kw vor min/max
        req = de.exact_kw if (getattr(de, "exact_kw", None) is not None) else max(de.min_kw or 0.0, de.max_kw or 0.0)
        req = max(0.0, float(req or 0.0))

        if req <= 0.0 or not bool(de.wants):
            allocations.append((cid, cons, 0.0))
            log_fn(f"[plan:must] {cid}: req=0 -> alloc=0.000 pv=0.000 grid=0.000 pv_left={pv_left:.3f}")
            if apply and not dry_run:
                try:
                    cons.apply_allocation(ctx, 0.0)
                except Exception as e:
                    log_fn(f"[plan] must_run apply 0.0 error for {cid}: {e}")
            continue

        # PV-Anteil bestimmen, Rest ist Grid (immer erlaubt für must_run)
        pv_share, grid_share, pv_kw_for_req = incremental_mix_for(req)
        alloc_kw = req  # diskrete Lasten erwarten volle Leistung

        # PV-Budget reduzieren, Grid summieren
        pv_left = max(0.0, pv_left - pv_kw_for_req)
        grid_part = max(0.0, alloc_kw - pv_kw_for_req)
        if grid_part > 0.0:
            grid_draw += grid_part

        allocations.append((cid, cons, alloc_kw))
        log_fn(f"[plan:must] {cid}: req={req:.3f} -> pv={pv_kw_for_req:.3f} grid={grid_part:.3f} pv_left={pv_left:.3f}")

        if apply and not dry_run:
            try:
                cons.apply_allocation(ctx, alloc_kw)
            except Exception as e:
                log_fn(f"[plan] must_run apply error for {cid}: {e}")

        log_fn(
            f"[DRY] {cid:12s} wants={bool(de.wants)} min={_fmt(de.min_kw)} max={_fmt(de.max_kw)} exact={_fmt(getattr(de, 'exact_kw', None))} must=True -> alloc={alloc_kw:.3f} (pv={pv_kw_for_req:.3f}, grid={grid_part:.3f}) | {getattr(de, 'reason', '')}")

    # ---------- 2) NORMALE LOADS wie bisher ----------
    for cid, cons, de in normals:
        wants = bool(de.wants)
        min_kw = max(de.min_kw or 0.0, 0.0)
        max_kw = max(de.max_kw or 0.0, 0.0)
        exact = getattr(de, "exact_kw", None)
        must = bool(getattr(de, "must_run", False))  # hier idR False
        reason = getattr(de, "reason", "")

        pv_alloc = 0.0
        grid_alloc = 0.0
        alloc_total = 0.0

        if not wants or (min_kw <= 0.0 and max_kw <= 0.0):
            allocations.append((cid, cons, 0.0))
            log_fn(f"[plan:alloc]  {cid}: pv=0.00 grid=0.00 total=0.00 pv_left={pv_left:.2f}")
            log_fn(
                f"[DRY] {cid:12s} wants={wants} min={_fmt(min_kw)} max={_fmt(max_kw)} exact={_fmt(exact)} must={must} -> alloc=0.000 (pv=0.000, grid=0.000) | {reason}")
            if apply and not dry_run:
                try:
                    cons.apply_allocation(ctx, 0.0)
                except Exception as e:
                    log_fn(f"[plan] error: apply_allocation({cid}, 0.000) -> {e}")
            continue

        if grid_free:
            # Negative Preise: volle Max-Leistung gestatten
            desired = max_kw
            pv_alloc = min(pv_left, desired)
            grid_alloc = max(0.0, desired - pv_alloc)
            pv_left -= pv_alloc
            alloc_total = pv_alloc + grid_alloc
            if grid_alloc > 0.0:
                grid_draw += grid_alloc
        else:
            # Deine bisherige PV-first-Logik
            need_from_pv = min(max_kw, pv_left)
            pv_alloc = max(0.0, need_from_pv)
            pv_left -= pv_alloc

            if must and pv_alloc < min_kw:
                if cid == "heater":  # bestehende Ausnahme
                    grid_alloc = 0.0
                else:
                    grid_alloc = max(0.0, min_kw - pv_alloc)
            else:
                grid_alloc = 0.0

            alloc_total = pv_alloc + grid_alloc
            if grid_alloc > 0.0:
                grid_draw += grid_alloc

        log_fn(
            f"[plan:alloc]  {cid}: pv={pv_alloc:.2f} grid={grid_alloc:.2f} total={alloc_total:.2f} pv_left={pv_left:.2f}")
        allocations.append((cid, cons, alloc_total))

        if apply and not dry_run:
            try:
                cons.apply_allocation(ctx, alloc_total)
            except Exception as e:
                log_fn(f"[plan] error: apply_allocation({cid}, {alloc_total:.3f}) -> {e}")

        log_fn(
            f"[DRY] {cid:12s} wants={wants} min={_fmt(min_kw)} max={_fmt(max_kw)} exact={_fmt(exact)} must={must} -> alloc={alloc_total:.3f} (pv={pv_alloc:.3f}, grid={grid_alloc:.3f}) | {reason}")


    return {"pv_left": pv_left, "grid_draw": grid_draw, "allocations": allocations}


# ----------------------------------------------------------------------------------
# Komfort-Wrapper
# ----------------------------------------------------------------------------------
def _discover_priority_order() -> List[str]:
    try:
        from ui_pages.settings import (  # type: ignore
            _prio_available_items as prio_available_items,
            _load_prio_ids as prio_load_ids,
            _prio_merge_with_stored as prio_merge,
        )
        available = prio_available_items()
        stored = prio_load_ids()
        order = prio_merge(stored, available)
        if "grid_feed" in order:
            order = [x for x in order if x != "grid_feed"] + ["grid_feed"]
        return order
    except Exception:
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
    ctx = Ctx(ts=now())
    order_eff = order or _discover_priority_order()
    return plan_and_allocate(ctx=ctx, order=order_eff, consumers=consumers, apply=apply, dry_run=dry_run, log=log, logger=logger)
