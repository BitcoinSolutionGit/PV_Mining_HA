from __future__ import annotations

import time
from typing import Callable, Dict

from services.ha_sensors import get_sensor_value
from services.heater_store import get_var as heat_get, resolve_entity_id as heat_resolve
from services.settings_store import get_var as set_get
from services.utils import load_state, update_state

STATE_KEY = "pv_ramp_up"


def _f(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("1", "true", "on", "yes", "y", "enabled")


def _state_defaults() -> Dict[str, float]:
    return {
        "stable_bonus_kw": 0.0,
        "candidate_bonus_kw": 0.0,
        "candidate_since_ts": 0.0,
        "probe_offset_kw": 0.0,
        "last_probe_ts": 0.0,
        "last_safety_reduce_ts": 0.0,
        "inactive_ticks": 0,
    }


def _load_block() -> tuple[dict, dict]:
    state = load_state() or {}
    raw = state.get(STATE_KEY) or {}
    block = _state_defaults()
    if isinstance(raw, dict):
        block.update(raw)

    for key in ("stable_bonus_kw", "candidate_bonus_kw", "candidate_since_ts", "probe_offset_kw",
                "last_probe_ts", "last_safety_reduce_ts"):
        block[key] = max(0.0, _f(block.get(key), 0.0))
    block["inactive_ticks"] = max(0, int(_f(block.get("inactive_ticks", 0), 0)))
    return state, block


def get_pv_ramp_snapshot() -> dict:
    """
    Read the current PV-ramp state without mutating it.
    The dashboard uses this so the Sankey can visualize the same temporary
    headroom model that the planner currently applies.
    """
    _state, block = _load_block()
    stable = max(0.0, _f(block.get("stable_bonus_kw"), 0.0))
    probe = max(0.0, _f(block.get("probe_offset_kw"), 0.0))
    candidate = max(0.0, _f(block.get("candidate_bonus_kw"), stable + probe))
    return {
        "stable_bonus_kw": stable,
        "probe_offset_kw": probe,
        "candidate_bonus_kw": candidate,
        "candidate_since_ts": max(0.0, _f(block.get("candidate_since_ts"), 0.0)),
        "inactive_ticks": max(0, int(_f(block.get("inactive_ticks", 0), 0))),
    }


def _save_block(state: dict, block: dict) -> None:
    normalized = {
        "stable_bonus_kw": max(0.0, _f(block.get("stable_bonus_kw"), 0.0)),
        "candidate_bonus_kw": max(0.0, _f(block.get("candidate_bonus_kw"), 0.0)),
        "candidate_since_ts": max(0.0, _f(block.get("candidate_since_ts"), 0.0)),
        "probe_offset_kw": max(0.0, _f(block.get("probe_offset_kw"), 0.0)),
        "last_probe_ts": max(0.0, _f(block.get("last_probe_ts"), 0.0)),
        "last_safety_reduce_ts": max(0.0, _f(block.get("last_safety_reduce_ts"), 0.0)),
        "inactive_ticks": max(0, int(_f(block.get("inactive_ticks", 0), 0))),
    }

    def _mut(st: dict):
        st[STATE_KEY] = normalized

    update_state(_mut)


def _result(block: dict, *, reason: str, cap_engaged: bool, heater_ok: bool) -> dict:
    stable = max(0.0, _f(block.get("stable_bonus_kw"), 0.0))
    probe = max(0.0, _f(block.get("probe_offset_kw"), 0.0))
    candidate = max(0.0, _f(block.get("candidate_bonus_kw"), stable + probe))
    return {
        "stable_bonus_kw": stable,
        "probe_offset_kw": probe,
        "candidate_bonus_kw": candidate,
        "candidate_since_ts": max(0.0, _f(block.get("candidate_since_ts"), 0.0)),
        "inactive_ticks": max(0, int(_f(block.get("inactive_ticks", 0), 0))),
        "cap_engaged": bool(cap_engaged),
        "heater_ok": bool(heater_ok),
        "reason": reason,
    }


def _heater_status() -> dict:
    enabled = bool(heat_get("enabled", False))
    auto = not bool(heat_get("manual_override", False))
    max_kw = max(0.0, _f(heat_get("max_power_heater", 0.0), 0.0))
    target_temp = _f(heat_get("wanted_water_temperature", 0.0), 0.0)
    kick_enabled = bool(heat_get("zero_export_kick_enabled", False))
    kick_kw = max(0.0, _f(heat_get("zero_export_kick_kw", 0.2), 0.2))

    temp_entity = (
        heat_resolve("sensor_water_temperature")
        or heat_resolve("input_warmwasser_cache")
        or ""
    ).strip()
    percent_entity = (
        heat_resolve("input_heizstab_cache")
        or heat_resolve("slider_water_heater_percent")
        or ""
    ).strip()

    temp_now = _f(get_sensor_value(temp_entity), None) if temp_entity else None
    pct_now = max(0.0, min(100.0, _f(get_sensor_value(percent_entity), 0.0))) if percent_entity else 0.0
    current_kw = max_kw * pct_now / 100.0 if max_kw > 0.0 else 0.0
    headroom_kw = max(0.0, max_kw - current_kw)

    reason = "ok"
    if not enabled:
        reason = "heater disabled"
    elif not auto:
        reason = "heater manual"
    elif max_kw <= 0.0:
        reason = "heater max power missing"
    elif not percent_entity:
        reason = "heater percent entity missing"
    elif temp_now is None:
        reason = "heater temperature missing"
    elif temp_now >= (target_temp - 0.5):
        reason = "heater target reached"

    return {
        "eligible": reason == "ok",
        "reason": reason,
        "enabled": enabled,
        "auto": auto,
        "max_kw": max_kw,
        "current_kw": current_kw,
        "headroom_kw": headroom_kw,
        "target_temp": target_temp,
        "temp_now": temp_now,
        "percent_entity": percent_entity,
        "kick_enabled": kick_enabled,
        "kick_kw": kick_kw,
    }


def _reset_block(block: dict) -> dict:
    clean = _state_defaults()
    clean["last_safety_reduce_ts"] = max(0.0, _f(block.get("last_safety_reduce_ts"), 0.0))
    return clean


def evaluate_pv_ramp_up(
    *,
    feed_kw: float,
    import_kw: float,
    battery_block: bool = False,
    logger: Callable[[str], None] | None = None,
) -> dict:
    log_fn = logger or (lambda *_: None)
    now_ts = time.time()

    allow = _truthy(set_get("allow_pv_ramp_up", True), True)
    cap_kw = max(0.0, _f(set_get("grid_export_cap_kw", 0.0), 0.0))
    settle_s = max(0, int(_f(set_get("pv_ramp_settle_s", 60), 60)))
    hysteresis_kw = max(0.0, _f(set_get("pv_ramp_hysteresis_w", 200.0), 200.0) / 1000.0)
    step_up_kw = max(0.0, _f(set_get("pv_ramp_step_up_kw", 0.40), 0.40))
    step_down_kw = max(0.0, _f(set_get("pv_ramp_step_down_kw", 0.60), 0.60))
    eps_kw = max(0.0, _f(set_get("pv_ramp_cap_epsilon_kw", 0.05), 0.05))

    state, block = _load_block()
    heater = _heater_status()
    measured_feed = max(0.0, _f(feed_kw, 0.0))
    measured_import = max(0.0, _f(import_kw, 0.0))
    cap_engaged_real = measured_feed >= max(0.0, cap_kw - eps_kw) if cap_kw > 0.0 else False
    zero_export_probe = (
        bool(heater.get("eligible"))
        and bool(heater.get("kick_enabled"))
        and _f(heater.get("current_kw"), 0.0) > 0.0
        and measured_import <= hysteresis_kw
        and measured_feed <= max(eps_kw, cap_kw + eps_kw)
    )
    cap_engaged = cap_engaged_real or zero_export_probe

    if not allow:
        block = _reset_block(block)
        _save_block(state, block)
        return _result(block, reason="disabled", cap_engaged=False, heater_ok=heater["eligible"])

    if not heater["eligible"]:
        block = _reset_block(block)
        _save_block(state, block)
        return _result(block, reason=heater["reason"], cap_engaged=cap_engaged, heater_ok=False)

    if battery_block:
        block = _reset_block(block)
        _save_block(state, block)
        return _result(block, reason="battery discharge", cap_engaged=cap_engaged, heater_ok=True)

    stable = max(0.0, _f(block.get("stable_bonus_kw"), 0.0))
    probe = max(0.0, _f(block.get("probe_offset_kw"), 0.0))
    candidate = max(0.0, _f(block.get("candidate_bonus_kw"), stable + probe))
    candidate_since = max(0.0, _f(block.get("candidate_since_ts"), 0.0))
    prev_candidate = candidate

    if measured_import > hysteresis_kw and (stable > 0.0 or probe > 0.0):
        reduce_by = max(step_down_kw, measured_import)
        stable = max(0.0, stable - reduce_by)
        probe = max(0.0, probe - reduce_by)
        candidate = stable + probe
        candidate_since = now_ts
        block.update(
            stable_bonus_kw=stable,
            probe_offset_kw=probe,
            candidate_bonus_kw=candidate,
            candidate_since_ts=candidate_since,
            inactive_ticks=0,
            last_safety_reduce_ts=now_ts,
        )
        _save_block(state, block)
        log_fn(
            f"[pv_ramp] safety-reduce import={measured_import:.3f}kW reduce={reduce_by:.3f}kW "
            f"stable={stable:.3f} probe={probe:.3f}"
        )
        return _result(block, reason="safety reduce", cap_engaged=cap_engaged, heater_ok=True)

    if not cap_engaged:
        block["probe_offset_kw"] = 0.0
        block["candidate_bonus_kw"] = stable
        block["candidate_since_ts"] = 0.0
        block["inactive_ticks"] = max(0, int(_f(block.get("inactive_ticks", 0), 0))) + 1
        if block["inactive_ticks"] >= 3:
            block = _reset_block(block)
            reason = "cap inactive reset"
        else:
            reason = "cap inactive hold"
        _save_block(state, block)
        return _result(block, reason=reason, cap_engaged=False, heater_ok=True)

    block["inactive_ticks"] = 0
    headroom_kw = max(0.0, _f(heater.get("headroom_kw"), 0.0))
    if headroom_kw > 0.0 and step_up_kw > 0.0:
        step = min(step_up_kw, headroom_kw)
        if step > 0.0:
            probe += step
            block["last_probe_ts"] = now_ts

    candidate = stable + probe
    if abs(candidate - prev_candidate) > hysteresis_kw:
        candidate_since = now_ts
    elif candidate > 0.0 and candidate_since <= 0.0:
        candidate_since = now_ts

    promoted = False
    if candidate > stable and candidate_since > 0.0 and (now_ts - candidate_since) >= settle_s:
        stable = candidate
        probe = 0.0
        candidate = stable
        candidate_since = now_ts
        promoted = True

    block.update(
        stable_bonus_kw=stable,
        probe_offset_kw=probe,
        candidate_bonus_kw=candidate,
        candidate_since_ts=candidate_since,
    )
    _save_block(state, block)

    if promoted:
        reason = "candidate stable"
    elif zero_export_probe and not cap_engaged_real:
        reason = "zero-export probing"
    else:
        reason = "probing"
    return _result(block, reason=reason, cap_engaged=True, heater_ok=True)
