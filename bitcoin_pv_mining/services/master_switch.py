from __future__ import annotations

import time

from services.consumers.battery import force_restore_battery_normal_mode
from services.cooling_store import get_cooling, set_cooling
from services.ha_entities import call_action, set_numeric_entity
from services.heater_store import resolve_entity_id as heat_resolve, set_vars as heat_set_vars
from services.miners_store import list_miners, request_miner_state, update_miner
from services.pv_ramp_up import reset_pv_ramp_up_state
from services.wallbox_store import get_var as wb_get, set_vars as wb_set_vars


def _safe_call(step: str, fn):
    try:
        return fn()
    except Exception as exc:
        print(f"[master_switch] {step} error: {exc}", flush=True)
        return False, f"{step} error: {exc}"


def _shutdown_miners(now_ts: float) -> tuple[bool, str]:
    miners = list_miners() or []
    if not miners:
        return True, "miners off"

    errors: list[str] = []
    for miner in miners:
        mid = str(miner.get("id") or "").strip()
        if not mid:
            continue
        ok, reason = request_miner_state(mid, False, now_ts=now_ts, enforce_runtime=False)
        if not ok:
            errors.append(f"{mid}: {reason}")

    if errors:
        return False, f"miners partial: {'; '.join(errors)}"
    return True, f"miners off ({len(miners)})"


def _shutdown_cooling(now_ts: float) -> tuple[bool, str]:
    cooling = get_cooling() or {}
    off_ent = str(cooling.get("action_off_entity") or "").strip()
    has_feedback = bool((cooling.get("resolved_state_entity") or cooling.get("state_entity") or "").strip())
    effective_on = bool(cooling.get("effective_on")) or bool(cooling.get("pending_on")) or bool(cooling.get("pending_off"))
    timeout_s = max(int(float(cooling.get("state_timeout_s") or 60)), 1)

    action_ok = True
    if off_ent:
        action_ok = bool(call_action(off_ent, False))

    set_cooling(
        on=False,
        pending_on=False,
        pending_off=(has_feedback and bool(cooling.get("effective_on"))),
        confirm_deadline_ts=(now_ts + timeout_s) if has_feedback and bool(cooling.get("effective_on")) else 0.0,
        fail_deadline_ts=(now_ts + (3 * timeout_s)) if has_feedback and bool(cooling.get("effective_on")) else 0.0,
        failed_phase="",
        last_transition_ts=now_ts if effective_on else cooling.get("last_transition_ts", 0.0),
    )

    if off_ent and not action_ok:
        return False, "cooling off failed"
    if effective_on and not off_ent:
        return False, "cooling off entity missing"
    return True, "cooling off"


def _shutdown_wallbox() -> tuple[bool, str]:
    off_ent = str(wb_get("action_off_entity", "") or "").strip()
    if not off_ent:
        return True, "wallbox stop skipped"

    ok = bool(call_action(off_ent, False))
    return (ok, "wallbox stop requested" if ok else "wallbox stop failed")


def _shutdown_heater() -> tuple[bool, str]:
    heat_set_vars(manual_override=True, manual_override_percent=0)
    entity_id = str(heat_resolve("input_heizstab_cache") or "").strip()
    if not entity_id:
        return True, "heater manual 0%"

    ok = bool(set_numeric_entity(entity_id, 0))
    return (ok, "heater manual 0%" if ok else "heater 0% send failed")


def shutdown_all_consumers() -> tuple[bool, str]:
    now_ts = time.time()
    reset_pv_ramp_up_state()

    steps = [
        _safe_call("miners", lambda: _shutdown_miners(now_ts)),
        _safe_call("cooling", lambda: _shutdown_cooling(now_ts)),
        _safe_call("wallbox", _shutdown_wallbox),
        _safe_call("heater", _shutdown_heater),
        _safe_call("battery", lambda: force_restore_battery_normal_mode("master switch restore battery normal mode")),
    ]

    problems = [msg for ok, msg in steps if not ok]
    for ok, msg in steps:
        print(f"[master_switch] ok={ok} {msg}", flush=True)

    if problems:
        return False, "Hauptschalter OFF - gespeichert. Verbraucher teilweise aus, Details im Log."
    return True, "Hauptschalter OFF - gespeichert. Verbraucher aus, Heater manuell 0 %."


def _arm_miners_auto(now_ts: float) -> tuple[bool, str]:
    miners = list_miners() or []
    if not miners:
        return True, "miners auto armed"

    errors: list[str] = []
    for miner in miners:
        mid = str(miner.get("id") or "").strip()
        if not mid:
            continue
        ok, reason = request_miner_state(mid, False, now_ts=now_ts, enforce_runtime=False)
        update_miner(mid, mode="auto")
        if not ok:
            errors.append(f"{mid}: {reason}")

    if errors:
        return False, f"miners auto partial: {'; '.join(errors)}"
    return True, f"miners auto armed ({len(miners)})"


def _arm_cooling_auto(now_ts: float) -> tuple[bool, str]:
    cooling = get_cooling() or {}
    off_ent = str(cooling.get("action_off_entity") or "").strip()
    has_feedback = bool((cooling.get("resolved_state_entity") or cooling.get("state_entity") or "").strip())
    effective_on = bool(cooling.get("effective_on")) or bool(cooling.get("pending_on")) or bool(cooling.get("pending_off"))
    timeout_s = max(int(float(cooling.get("state_timeout_s") or 60)), 1)

    action_ok = True
    if off_ent:
        action_ok = bool(call_action(off_ent, False))

    set_cooling(
        mode="auto",
        on=False,
        pending_on=False,
        pending_off=(has_feedback and bool(cooling.get("effective_on"))),
        confirm_deadline_ts=(now_ts + timeout_s) if has_feedback and bool(cooling.get("effective_on")) else 0.0,
        fail_deadline_ts=(now_ts + (3 * timeout_s)) if has_feedback and bool(cooling.get("effective_on")) else 0.0,
        failed_phase="",
        last_transition_ts=now_ts if effective_on else cooling.get("last_transition_ts", 0.0),
    )

    if off_ent and not action_ok:
        return False, "cooling auto off failed"
    return True, "cooling auto armed"


def _arm_wallbox_auto() -> tuple[bool, str]:
    off_ent = str(wb_get("action_off_entity", "") or "").strip()
    wb_set_vars(mode="auto")
    if not off_ent:
        return True, "wallbox auto armed"

    ok = bool(call_action(off_ent, False))
    return (ok, "wallbox auto armed" if ok else "wallbox auto off failed")


def _arm_heater_auto() -> tuple[bool, str]:
    heat_set_vars(manual_override=False, manual_override_percent=0)
    entity_id = str(heat_resolve("input_heizstab_cache") or "").strip()
    if not entity_id:
        return True, "heater auto 0%"

    ok = bool(set_numeric_entity(entity_id, 0))
    return (ok, "heater auto 0%" if ok else "heater auto 0% send failed")


def arm_all_consumers_auto() -> tuple[bool, str]:
    now_ts = time.time()
    reset_pv_ramp_up_state()

    steps = [
        _safe_call("miners_auto", lambda: _arm_miners_auto(now_ts)),
        _safe_call("cooling_auto", lambda: _arm_cooling_auto(now_ts)),
        _safe_call("wallbox_auto", _arm_wallbox_auto),
        _safe_call("heater_auto", _arm_heater_auto),
        _safe_call("battery", lambda: force_restore_battery_normal_mode("master switch arm battery normal mode")),
    ]

    problems = [msg for ok, msg in steps if not ok]
    for ok, msg in steps:
        print(f"[master_switch] ok={ok} {msg}", flush=True)

    if problems:
        return False, "Hauptschalter AKTIV - Automatik an, Verbraucher auf OFF initialisiert. Details im Log."
    return True, "Hauptschalter AKTIV - Automatik an, Verbraucher OFF, Heater Auto 0 %."
