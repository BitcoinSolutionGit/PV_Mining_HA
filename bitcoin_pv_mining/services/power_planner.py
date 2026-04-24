# services/power_planner.py
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from services.consumers.base import Ctx, Desire, BaseConsumer, now
from services.consumers.registry import get_consumer_for_id

import os
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.settings_store import get_var as set_get
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.energy_mix import surplus_strict_kw as _surplus_strict_kw, incremental_mix_for, read_energy_flows
from services.export_cap_boost import try_export_cap_boost
from services.pv_ramp_up import evaluate_pv_ramp_up
from services.sensor_mapping import resolve_sensor_id as resolve_runtime_sensor_id

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
    return resolve_runtime_sensor_id(key, allow_mock=True)


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
        is_on = bool(c.get("effective_on")) if "effective_on" in c else (bool(ha_on) if ha_on is not None else _truthy(c.get("on"), False))
        if is_on and pkw > 0.0:
            now_kw += pkw
    except Exception:
        pass

    # Miner (diskret)
    try:
        from services.miners_store import list_miners
        for m in (list_miners() or []):
            if bool(m.get("effective_on", m.get("on"))):
                now_kw += _f(m.get("power_kw"), 0.0)
    except Exception:
        pass

    # Wallbox/Battery könntest du später ergänzen
    return max(0.0, now_kw)


def _battery_discharge_kw_now() -> float:
    try:
        _pv_kw, _imp_kw, _feed_kw, bat_kw, _surplus_direct = read_energy_flows()
        return max(0.0, _f(bat_kw, 0.0))
    except Exception:
        return 0.0


def _miner_min_run_s(mid: str, default: int = 60) -> int:
    raw = set_get(f"miner.{mid}.min_run_min", None)
    if raw is not None:
        try:
            return max(0, int(float(raw) * 60.0))
        except Exception:
            return default
    return int(_f(set_get("miner_min_run_s", default), default))


def _discrete_runtime_meta(cid: str) -> Optional[dict]:
    if cid == "cooling":
        try:
            from services.cooling_store import get_cooling

            c = get_cooling() or {}
            return {
                "kind": "cooling",
                "actual_on": bool(c.get("effective_on")) or bool(c.get("pending_on")) or bool(c.get("on")),
                "last_flip_ts": _f(c.get("last_transition_ts"), 0.0),
                "nominal_kw": _f(c.get("power_kw"), 0.0),
                "min_run_s": int(_f(set_get("cooling_min_run_s", 20), 20)),
                "min_off_s": int(_f(set_get("cooling_min_off_s", 20), 20)),
            }
        except Exception:
            return None

    if cid.startswith("miner:"):
        try:
            from services.miners_store import list_miners

            mid = cid.split(":", 1)[1]
            miner = next((m for m in (list_miners() or []) if m.get("id") == mid), None)
            if not miner:
                return None
            return {
                "kind": "miner",
                "actual_on": bool(miner.get("effective_on", miner.get("on"))),
                "last_flip_ts": _f(miner.get("last_flip_ts"), 0.0),
                "nominal_kw": _f(miner.get("power_kw"), 0.0),
                "min_run_s": _miner_min_run_s(mid),
                "min_off_s": int(_f(set_get("miner_min_off_s", 20), 20)),
            }
        except Exception:
            return None

    return None


def _cooling_has_dependent_miner(
    *,
    collected: List[Tuple[str, BaseConsumer, Desire]],
    pv_left: float,
    grid_free: bool,
) -> bool:
    try:
        from services.cooling_store import get_cooling
        from services.miners_store import list_miners
    except Exception:
        return False

    cooling = get_cooling() or {}
    cooling_kw = max(0.0, _f(cooling.get("power_kw"), 0.0))
    miners = {f"miner:{m.get('id')}": m for m in (list_miners() or []) if m.get("id")}

    for cid, _cons, desire in collected:
        miner = miners.get(cid)
        if not miner:
            continue
        if not _truthy(miner.get("require_cooling"), False):
            continue
        if bool(miner.get("effective_on", miner.get("on"))):
            return True

        req = desire.exact_kw if getattr(desire, "exact_kw", None) is not None else max(desire.min_kw or 0.0, desire.max_kw or 0.0)
        req = max(0.0, float(req or 0.0))
        if not bool(desire.wants) or req <= 0.0:
            continue

        combined_kw = cooling_kw + req
        if grid_free or (pv_left + 1e-9 >= combined_kw):
            return True

    return False


def _allocate_discrete_load(
    *,
    cid: str,
    desire: Desire,
    pv_left: float,
    grid_free: bool,
    battery_block: bool,
    now_ts: float,
) -> tuple[float, float, float, str]:
    meta = _discrete_runtime_meta(cid) or {}
    req = desire.exact_kw if desire.exact_kw is not None else max(desire.min_kw or 0.0, desire.max_kw or 0.0)
    req = max(0.0, float(req or 0.0))

    actual_on = bool(meta.get("actual_on"))
    last_flip_ts = _f(meta.get("last_flip_ts"), 0.0)
    nominal_kw = max(0.0, _f(meta.get("nominal_kw"), 0.0))
    min_run_s = int(_f(meta.get("min_run_s"), 0.0))
    min_off_s = int(_f(meta.get("min_off_s"), 0.0))
    elapsed = max(0.0, now_ts - last_flip_ts) if last_flip_ts > 0.0 else 0.0

    locked_on = actual_on and (last_flip_ts > 0.0) and (elapsed < max(0, min_run_s))
    locked_off = (not actual_on) and (last_flip_ts > 0.0) and (elapsed < max(0, min_off_s))
    wants_on = bool(desire.wants) and req > 0.0

    decision_reason = ""
    if battery_block:
        if locked_on:
            decision_reason = f"battery-backed min-run lock {max(0, int(min_run_s - elapsed))}s"
            alloc_total = max(req, nominal_kw)
        else:
            decision_reason = "battery discharge block"
            alloc_total = 0.0
    elif locked_on:
        decision_reason = f"min-run lock {max(0, int(min_run_s - elapsed))}s"
        alloc_total = max(req, nominal_kw)
    elif locked_off:
        decision_reason = f"min-off lock {max(0, int(min_off_s - elapsed))}s"
        alloc_total = 0.0
    elif not wants_on:
        decision_reason = "desire off"
        alloc_total = 0.0
    elif grid_free:
        decision_reason = "negative grid price"
        alloc_total = req
    elif pv_left + 1e-9 >= req:
        decision_reason = "pv budget available"
        alloc_total = req
    else:
        decision_reason = "insufficient pv budget"
        alloc_total = 0.0

    pv_alloc = min(pv_left, alloc_total)
    grid_alloc = max(0.0, alloc_total - pv_alloc)
    return alloc_total, pv_alloc, grid_alloc, decision_reason


def _consumer_reserves_pv_budget(cid: str, cons: BaseConsumer) -> bool:
    flag = getattr(cons, "reserves_pv_budget", None)
    if flag is not None:
        return bool(flag)
    return cid != "battery"


def _cooling_active_need_now() -> bool:
    try:
        from services.miners_store import list_miners

        return any(
            _truthy(m.get("enabled"), False)
            and _truthy(m.get("effective_on", m.get("on")), False)
            and _truthy(m.get("require_cooling"), False)
            for m in (list_miners() or [])
        )
    except Exception:
        return False


def _sanitize_priority_order(order: List[str]) -> List[str]:
    """
    Cooling is no longer a standalone planner item. It is handled implicitly
    by miners that require it.
    """
    cleaned = [cid for cid in (order or []) if cid != "cooling"]
    if "grid_feed" in cleaned:
        cleaned = [cid for cid in cleaned if cid != "grid_feed"] + ["grid_feed"]
    return cleaned



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
    order = _sanitize_priority_order(order)

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
    measured_surplus_kw = max(surplus_raw - guard_kw, 0.0)
    feed_kw = 0.0
    import_kw = 0.0
    try:
        _pv_dbg, _imp_dbg, _feed_dbg = _read_pv_import_feed()
        import_kw = max(_f(_imp_dbg, 0.0), 0.0)
        feed_kw = max(_f(_feed_dbg, 0.0), 0.0)
    except Exception:
        pass

    battery_block_kw = _battery_discharge_kw_now()
    battery_block = battery_block_kw > 0.05
    log_fn(f"[plan] battery_discharge={battery_block_kw:.3f} kW -> battery_block={battery_block}")
    if battery_block:
        log_fn("[plan] battery discharge active -> flexible consumers are cut back; locked miners may continue until min-run expires")

    try:
        pv_ramp = evaluate_pv_ramp_up(
            feed_kw=feed_kw,
            import_kw=import_kw,
            battery_block=battery_block,
            logger=log_fn,
        )
    except Exception as e:
        log_fn(f"[pv_ramp] error: {e}")
        pv_ramp = {
            "stable_bonus_kw": 0.0,
            "probe_offset_kw": 0.0,
            "candidate_bonus_kw": 0.0,
            "candidate_since_ts": 0.0,
            "inactive_ticks": 0,
            "cap_engaged": False,
            "heater_ok": False,
            "reason": "error",
        }

    pv_left: float = max(0.0, measured_surplus_kw + _f(pv_ramp.get("stable_bonus_kw"), 0.0))
    grid_draw: float = 0.0
    allocations: List[Tuple[str, BaseConsumer, float]] = []

    eff_grid_cost = _f(elec_price(), 0.0) + _f(elec_get("network_fee_down_value", 0.0), 0.0)
    grid_free = (eff_grid_cost <= 0.0)

    # expose planner facts to consumers
    for k, v in (
            ("surplus_kw", pv_left),  # PV-Überschuss nach Guard / Ramp-Up
            ("surplus_measured_kw", measured_surplus_kw),
            ("surplus_effective_kw", pv_left),
            ("grid_cost_eur_kwh", eff_grid_cost),  # effektiver Grid-preis (incl. fee_down)
            ("pv_kw_raw", pv_kw),  # (optional) aktuelle PV-Produktion
            ("surplus_raw_kw", surplus_raw),  # (optional) Überschuss vor Guard
            ("pv_ramp_bonus_kw", _f(pv_ramp.get("stable_bonus_kw"), 0.0)),
            ("pv_ramp_probe_offset_kw", _f(pv_ramp.get("probe_offset_kw"), 0.0)),
            ("pv_ramp_candidate_kw", _f(pv_ramp.get("candidate_bonus_kw"), 0.0)),
            ("battery_discharge_kw", battery_block_kw),
            ("battery_block", battery_block),
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
        ctx["surplus_kw"] = pv_left  # strikter PV-Überschuss nach Guard / Ramp-Up
        ctx["surplus_measured_kw"] = measured_surplus_kw
        ctx["surplus_effective_kw"] = pv_left
        ctx["grid_cost_eur_kwh"] = eff_grid_cost
        ctx["pv_ramp_bonus_kw"] = _f(pv_ramp.get("stable_bonus_kw"), 0.0)
        ctx["pv_ramp_probe_offset_kw"] = _f(pv_ramp.get("probe_offset_kw"), 0.0)
        ctx["pv_ramp_candidate_kw"] = _f(pv_ramp.get("candidate_bonus_kw"), 0.0)
        ctx["battery_discharge_kw"] = battery_block_kw
        ctx["battery_block"] = battery_block
    except Exception:
        pass

    log_fn(f"[plan] grid_cost={eff_grid_cost:.4f} €/kWh -> grid_free={grid_free}")

    log_fn(f"[plan] order={order}")
    log_fn(f"[plan] start surplus={pv_left:.3f} kW")
    log_fn(f"[plan:strict] total={total_load:.3f} kW  ctrl_now={ctrl_now:.3f} kW  base={base_load:.3f} kW  pv={pv_kw:.3f} kW  raw={surplus_raw:.3f} kW")
    log_fn(f"[plan:guard] guard={guard_kw:.3f} kW (w={guard_w:.0f}W, pct={guard_pct:.3f}) -> measured={measured_surplus_kw:.3f} kW")
    log_fn(
        f"[pv_ramp] measured={measured_surplus_kw:.3f} bonus={_f(pv_ramp.get('stable_bonus_kw'), 0.0):.3f} "
        f"probe={_f(pv_ramp.get('probe_offset_kw'), 0.0):.3f} candidate={_f(pv_ramp.get('candidate_bonus_kw'), 0.0):.3f} "
        f"effective={pv_left:.3f} cap={int(bool(pv_ramp.get('cap_engaged')))} heater={int(bool(pv_ramp.get('heater_ok')))} "
        f"inactive={int(_f(pv_ramp.get('inactive_ticks', 0), 0))} reason={pv_ramp.get('reason', '')}"
    )

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

    now_ts = _f(getattr(ctx, "ts", 0.0), 0.0) or now()
    hard_must_runs = [(cid, cons, de) for (cid, cons, de) in collected if cid == "house" and bool(getattr(de, "must_run", False))]
    remaining = [(cid, cons, de) for (cid, cons, de) in collected if not (cid == "house" and bool(getattr(de, "must_run", False)))]

    # ---------- 1) HARTE MUST-RUNS (nur Hauslast) ----------
    for cid, cons, de in hard_must_runs:
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

        pv_alloc = min(pv_left, req)
        pv_left = max(0.0, pv_left - pv_alloc)
        grid_part = max(0.0, req - pv_alloc)
        if grid_part > 0.0:
            grid_draw += grid_part

        allocations.append((cid, cons, req))
        log_fn(f"[plan:must] {cid}: req={req:.3f} -> pv={pv_alloc:.3f} grid={grid_part:.3f} pv_left={pv_left:.3f}")

        if apply and not dry_run:
            try:
                cons.apply_allocation(ctx, req)
            except Exception as e:
                log_fn(f"[plan] must_run apply error for {cid}: {e}")

        log_fn(
            f"[DRY] {cid:12s} wants={bool(de.wants)} min={_fmt(de.min_kw)} max={_fmt(de.max_kw)} exact={_fmt(getattr(de, 'exact_kw', None))} must=True -> alloc={req:.3f} (pv={pv_alloc:.3f}, grid={grid_part:.3f}) | {getattr(de, 'reason', '')}")

    # ---------- 2) ÜBRIGE LASTEN PRIORISIERT ----------
    for cid, cons, de in remaining:
        wants = bool(de.wants)
        min_kw = max(de.min_kw or 0.0, 0.0)
        max_kw = max(de.max_kw or 0.0, 0.0)
        exact = getattr(de, "exact_kw", None)
        must = bool(getattr(de, "must_run", False))  # hier idR False
        reason = getattr(de, "reason", "")

        pv_alloc = 0.0
        grid_alloc = 0.0
        alloc_total = 0.0

        if cid in ("grid_feed", "inflow"):
            continue

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

        if not _consumer_reserves_pv_budget(cid, cons):
            reason = f"{reason} | passive observer, no budget reservation" if reason else "passive observer, no budget reservation"
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

        discrete_meta = _discrete_runtime_meta(cid)

        if discrete_meta:
            alloc_total, pv_alloc, grid_alloc, policy_reason = _allocate_discrete_load(
                cid=cid,
                desire=de,
                pv_left=pv_left,
                grid_free=grid_free,
                battery_block=battery_block and cid != "house",
                now_ts=now_ts,
            )
            pv_left = max(0.0, pv_left - pv_alloc)
            if grid_alloc > 0.0:
                grid_draw += grid_alloc
            reason = f"{reason} | {policy_reason}" if reason else policy_reason
        else:
            if battery_block and cid != "house":
                alloc_total = 0.0
                reason = f"{reason} | battery discharge block" if reason else "battery discharge block"
            else:
                if grid_free:
                    desired = max_kw
                    pv_alloc = min(pv_left, desired)
                    grid_alloc = max(0.0, desired - pv_alloc)
                    pv_left -= pv_alloc
                    alloc_total = pv_alloc + grid_alloc
                    if grid_alloc > 0.0:
                        grid_draw += grid_alloc
                else:
                    desired = min(max_kw, pv_left)
                    pv_alloc = max(0.0, desired)
                    if pv_alloc + 1e-9 < min_kw:
                        pv_alloc = 0.0
                    pv_left -= pv_alloc
                    grid_alloc = 0.0
                    alloc_total = pv_alloc

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

    # Cooling is handled implicitly by miners, but still needs a central
    # cleanup path when the last cooling-dependent miner is already off.
    cooling_needed_now = _cooling_active_need_now()
    if not cooling_needed_now:
        cool_cons = _get_cons("cooling")
        if cool_cons:
            log_fn("[plan] cooling cleanup: no active cooling-dependent miner -> target OFF")
            if apply and not dry_run:
                try:
                    cool_cons.apply_allocation(ctx, 0.0)
                except Exception as e:
                    log_fn(f"[plan] error: cooling cleanup OFF -> {e}")


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
        return _sanitize_priority_order(order)
    except Exception:
        return ["house", "battery", "heater", "wallbox", "grid_feed"]


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
