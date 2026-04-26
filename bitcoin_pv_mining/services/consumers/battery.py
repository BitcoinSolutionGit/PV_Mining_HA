from __future__ import annotations

import time

from services.consumers.base import BaseConsumer, Desire, Ctx
from services.ha_entities import call_action, get_entity_state, set_numeric_entity
from services.ha_sensors import get_sensor_value
from services.battery_store import (
    clear_override_state,
    get_override_state,
    get_var as bat_get,
    set_override_state,
)


def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _ctx_num(ctx: Ctx | dict | None, name: str, default=None):
    try:
        val = getattr(ctx, name)
        return default if val is None else float(val)
    except Exception:
        pass
    try:
        val = ctx.get(name, default)
        return default if val is None else float(val)
    except Exception:
        return default


def _entity_str(key: str) -> str:
    return str(bat_get(key, "") or "").strip()


def _bool_state(raw) -> bool | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("on", "true", "1", "charging", "enabled"):
        return True
    if s in ("off", "false", "0", "disabled"):
        return False
    try:
        return float(s) > 0.0
    except Exception:
        return None


def _snapshot_numeric(entity_id: str) -> float | None:
    raw = get_entity_state(entity_id)
    try:
        return None if raw is None else float(raw)
    except Exception:
        return None


def _retry_blocked(state: dict, now_ts: float) -> bool:
    return now_ts < _num(state.get("next_retry_ts"), 0.0)


class BatteryConsumer(BaseConsumer):
    id = "battery"
    label = "Battery"
    reserves_pv_budget = False

    def _read_soc(self) -> float:
        ent = _entity_str("soc_entity")
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _read_voltage(self) -> float:
        ent = _entity_str("voltage_entity") or _entity_str("dc_voltage_entity")
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _read_current(self) -> float:
        ent = _entity_str("current_entity") or _entity_str("dc_current_entity")
        return _num(get_sensor_value(ent) if ent else None, 0.0)

    def _measured_power_kw(self) -> float | None:
        v = self._read_voltage()
        a = self._read_current()
        if abs(v) <= 1e-6 or abs(a) <= 1e-6:
            p_ent = _entity_str("power_entity")
            if p_ent:
                return _num(get_sensor_value(p_ent), 0.0)
            return None
        return (v * a) / 1000.0

    def _target_soc(self) -> float:
        return _num(bat_get("target_soc", 90.0), 90.0)

    def _max_charge_kw(self) -> float:
        return max(0.0, _num(bat_get("max_charge_kw", 0.0), 0.0))

    def _neg_control_enabled(self) -> bool:
        return bool(bat_get("neg_price_control_enabled", False))

    def _charge_power_negative_w(self) -> float | None:
        raw = bat_get("charge_power_negative_w", None)
        val = _num(raw, None)
        if val is not None and val > 0.0:
            return val
        fallback_kw = self._max_charge_kw()
        return (fallback_kw * 1000.0) if fallback_kw > 0.0 else None

    def _validate_config(self) -> tuple[bool, str]:
        controls = 0

        if _entity_str("discharge_limit_entity"):
            controls += 1

        charge_allowed_entity = _entity_str("charge_allowed_entity")
        charge_allowed_on = _entity_str("charge_allowed_on_entity")
        charge_allowed_off = _entity_str("charge_allowed_off_entity")
        if charge_allowed_entity or charge_allowed_on or charge_allowed_off:
            can_enable = bool(charge_allowed_on or charge_allowed_entity)
            can_disable = bool(charge_allowed_off or charge_allowed_entity)
            if not can_enable or not can_disable:
                return False, "charge-allowed control needs both ON and OFF path"
            controls += 1

        charge_power_entity = _entity_str("charge_power_entity")
        if charge_power_entity:
            if self._charge_power_negative_w() is None:
                return False, "charge-power entity needs negative value or max_charge_kw"
            controls += 1

        if _entity_str("target_soc_entity"):
            controls += 1

        if controls <= 0:
            return False, "negative-price control enabled but no control entities configured"
        return True, ""

    def _snapshot_controls(self) -> tuple[dict, list[str]]:
        remembered: dict[str, object] = {}
        issues: list[str] = []

        discharge_entity = _entity_str("discharge_limit_entity")
        if discharge_entity:
            val = _snapshot_numeric(discharge_entity)
            if val is None and bat_get("discharge_limit_normal_w", None) is None:
                issues.append("discharge limit current value unreadable and no normal value configured")
            remembered["discharge_limit"] = {"entity_id": discharge_entity, "value": val}

        charge_allowed_entity = _entity_str("charge_allowed_entity")
        charge_allowed_on = _entity_str("charge_allowed_on_entity")
        charge_allowed_off = _entity_str("charge_allowed_off_entity")
        if charge_allowed_entity:
            remembered["charge_allowed"] = {
                "entity_id": charge_allowed_entity,
                "value": _bool_state(get_entity_state(charge_allowed_entity)),
                "on_entity": charge_allowed_on,
                "off_entity": charge_allowed_off,
            }
        elif charge_allowed_on or charge_allowed_off:
            remembered["charge_allowed"] = {
                "entity_id": "",
                "value": None,
                "on_entity": charge_allowed_on,
                "off_entity": charge_allowed_off,
            }

        charge_power_entity = _entity_str("charge_power_entity")
        if charge_power_entity:
            val = _snapshot_numeric(charge_power_entity)
            if val is None and bat_get("charge_power_normal_w", None) is None:
                issues.append("charge power current value unreadable and no normal value configured")
            remembered["charge_power"] = {"entity_id": charge_power_entity, "value": val}

        target_soc_entity = _entity_str("target_soc_entity")
        if target_soc_entity:
            val = _snapshot_numeric(target_soc_entity)
            if val is None and bat_get("target_soc_normal_pct", None) is None and bat_get("target_soc", None) is None:
                issues.append("target SoC current value unreadable and no normal value configured")
            remembered["target_soc"] = {"entity_id": target_soc_entity, "value": val}

        return remembered, issues

    def _set_charge_allowed(self, enabled: bool, remembered: dict | None = None) -> tuple[bool, str]:
        snap = remembered if isinstance(remembered, dict) else {}
        use_snapshot_only = bool(snap)
        if use_snapshot_only:
            charge_allowed_entity = str(snap.get("entity_id") or "").strip()
            action_ent = str((snap.get("on_entity") if enabled else snap.get("off_entity")) or "").strip()
        else:
            charge_allowed_entity = _entity_str("charge_allowed_entity")
            action_ent = _entity_str("charge_allowed_on_entity") if enabled else _entity_str("charge_allowed_off_entity")

        if action_ent:
            ok = call_action(action_ent, True)
            return ok, f"{action_ent} -> {'on' if enabled else 'off'}"
        if charge_allowed_entity:
            ok = call_action(charge_allowed_entity, enabled)
            return ok, f"{charge_allowed_entity} -> {'on' if enabled else 'off'}"
        return False, "no charge-allowed entity configured"

    def _apply_targets(self, remembered: dict) -> tuple[bool, str]:
        steps: list[tuple[str, bool]] = []

        discharge_entity = _entity_str("discharge_limit_entity")
        if discharge_entity:
            ok = set_numeric_entity(discharge_entity, _num(bat_get("discharge_limit_negative_w", 0.0), 0.0))
            steps.append((f"{discharge_entity}=negative discharge limit", ok))
            if not ok:
                return False, steps[-1][0]

        charge_allowed_entity = _entity_str("charge_allowed_entity")
        charge_allowed_on = _entity_str("charge_allowed_on_entity")
        charge_allowed_off = _entity_str("charge_allowed_off_entity")
        if charge_allowed_entity or charge_allowed_on or charge_allowed_off:
            ok, msg = self._set_charge_allowed(True)
            steps.append((msg, ok))
            if not ok:
                return False, msg

        charge_power_entity = _entity_str("charge_power_entity")
        charge_power_negative_w = self._charge_power_negative_w()
        if charge_power_entity and charge_power_negative_w is not None:
            ok = set_numeric_entity(charge_power_entity, charge_power_negative_w)
            steps.append((f"{charge_power_entity}=negative charge power", ok))
            if not ok:
                return False, steps[-1][0]

        target_soc_entity = _entity_str("target_soc_entity")
        if target_soc_entity:
            target_soc_negative = _num(bat_get("target_soc_negative_pct", 100.0), 100.0)
            ok = set_numeric_entity(target_soc_entity, target_soc_negative)
            steps.append((f"{target_soc_entity}=negative target soc", ok))
            if not ok:
                return False, steps[-1][0]

        if remembered:
            return True, "override applied"
        return True, "override applied"

    def _restore_targets(self, remembered: dict, reason: str, now_ts: float) -> tuple[bool, str]:
        errors: list[str] = []

        discharge_info = remembered.get("discharge_limit") if isinstance(remembered.get("discharge_limit"), dict) else {}
        discharge_entity = str((discharge_info or {}).get("entity_id") or _entity_str("discharge_limit_entity") or "").strip()
        if discharge_entity:
            target = bat_get("discharge_limit_normal_w", None)
            if target is None:
                target = (discharge_info or {}).get("value", remembered.get("discharge_limit", None))
            if target is None:
                errors.append("discharge limit restore target missing")
            elif not set_numeric_entity(discharge_entity, float(target)):
                errors.append(f"restore {discharge_entity}")

        charge_info = remembered.get("charge_allowed") if isinstance(remembered.get("charge_allowed"), dict) else {}
        charge_allowed_entity = str((charge_info or {}).get("entity_id") or _entity_str("charge_allowed_entity") or "").strip()
        charge_allowed_on = str((charge_info or {}).get("on_entity") or _entity_str("charge_allowed_on_entity") or "").strip()
        charge_allowed_off = str((charge_info or {}).get("off_entity") or _entity_str("charge_allowed_off_entity") or "").strip()
        if charge_allowed_entity or charge_allowed_on or charge_allowed_off:
            remembered_bool = _bool_state((charge_info or {}).get("value", remembered.get("charge_allowed")))
            target_bool = False if remembered_bool is None else remembered_bool
            ok, msg = self._set_charge_allowed(target_bool, charge_info)
            if not ok:
                errors.append(f"restore {msg}")

        charge_power_info = remembered.get("charge_power") if isinstance(remembered.get("charge_power"), dict) else {}
        charge_power_entity = str((charge_power_info or {}).get("entity_id") or _entity_str("charge_power_entity") or "").strip()
        if charge_power_entity:
            target = bat_get("charge_power_normal_w", None)
            if target is None:
                target = (charge_power_info or {}).get("value", remembered.get("charge_power", None))
            if target is None:
                errors.append("charge power restore target missing")
            elif not set_numeric_entity(charge_power_entity, float(target)):
                errors.append(f"restore {charge_power_entity}")

        target_soc_info = remembered.get("target_soc") if isinstance(remembered.get("target_soc"), dict) else {}
        target_soc_entity = str((target_soc_info or {}).get("entity_id") or _entity_str("target_soc_entity") or "").strip()
        if target_soc_entity:
            target = bat_get("target_soc_normal_pct", None)
            if target is None:
                target = (target_soc_info or {}).get("value", remembered.get("target_soc", None))
            if target is None:
                target = bat_get("target_soc", None)
            if target is None:
                errors.append("target SoC restore target missing")
            elif not set_numeric_entity(target_soc_entity, float(target)):
                errors.append(f"restore {target_soc_entity}")

        if errors:
            set_override_state(
                active=False,
                status="restore_failed",
                error="; ".join(errors),
                last_action_at=now_ts,
                next_retry_ts=(now_ts + 30.0),
                remembered=remembered or {},
            )
            return False, f"{reason}: {'; '.join(errors)}"

        clear_override_state()
        return True, reason

    def _activate_negative_price_control(self, grid_cost: float, now_ts: float) -> tuple[bool, str]:
        ok, reason = self._validate_config()
        if not ok:
            set_override_state(
                active=False,
                status="apply_failed",
                error=reason,
                last_action_at=now_ts,
                next_retry_ts=(now_ts + 30.0),
                last_grid_price_eur_kwh=grid_cost,
                remembered={},
            )
            return False, reason

        remembered, issues = self._snapshot_controls()
        if issues:
            reason = "; ".join(issues)
            set_override_state(
                active=False,
                status="apply_failed",
                error=reason,
                last_action_at=now_ts,
                next_retry_ts=(now_ts + 30.0),
                last_grid_price_eur_kwh=grid_cost,
                remembered=remembered,
            )
            return False, reason

        ok, reason = self._apply_targets(remembered)
        if ok:
            set_override_state(
                active=True,
                status="active",
                error="",
                activated_at=now_ts,
                last_action_at=now_ts,
                next_retry_ts=0.0,
                last_grid_price_eur_kwh=grid_cost,
                remembered=remembered,
            )
            return True, reason

        rollback_ok, rollback_reason = self._restore_targets(remembered, "rollback after apply failure", now_ts)
        if rollback_ok:
            set_override_state(
                active=False,
                status="apply_failed",
                error=reason,
                last_action_at=now_ts,
                next_retry_ts=(now_ts + 30.0),
                last_grid_price_eur_kwh=grid_cost,
                remembered={},
            )
            return False, reason

        return False, f"{reason}; {rollback_reason}"

    def compute_desire(self, ctx: Ctx) -> Desire:
        soc = self._read_soc()
        target = self._target_soc()
        max_kw = self._max_charge_kw()
        surplus = max(0.0, _ctx_num(ctx, "surplus_kw", 0.0) or 0.0)
        grid_c = _ctx_num(ctx, "grid_cost_eur_kwh", None)
        allow_grid_charge = bool(bat_get("allow_grid_charge", False)) or self._neg_control_enabled()

        if max_kw <= 0:
            return Desire(False, 0.0, 0.0, reason="no max power configured")
        if soc >= target:
            return Desire(False, 0.0, 0.0, reason=f"SoC {soc:.1f}% ≥ target {target:.1f}%")

        if allow_grid_charge and (grid_c is not None) and (grid_c <= 0.0):
            return Desire(True, 0.0, max_kw, reason="negative grid price, grid charge allowed")

        if surplus <= 0.0:
            return Desire(False, 0.0, 0.0, reason="no PV surplus")

        want = min(max_kw, surplus)
        return Desire(True, 0.0, want, reason=f"charge up to {want:.3f} kW (SoC {soc:.1f}% < {target:.1f}%)")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        now_ts = time.time()
        state = get_override_state()
        grid_cost = _ctx_num(ctx, "grid_cost_eur_kwh", None)
        control_enabled = self._neg_control_enabled()

        if state.get("status") == "restore_failed" and not _retry_blocked(state, now_ts):
            ok, reason = self._restore_targets(state.get("remembered") or {}, "retry restore", now_ts)
            print(f"[battery] restore retry -> ok={ok} reason={reason}", flush=True)
            state = get_override_state()

        if not control_enabled or grid_cost is None:
            if state.get("active") or state.get("status") == "restore_failed":
                if state.get("status") == "restore_failed" and _retry_blocked(state, now_ts):
                    print(f"[battery] restore cooldown active until {state.get('next_retry_ts')}", flush=True)
                    return
                ok, reason = self._restore_targets(
                    state.get("remembered") or {},
                    "restore normal mode" if not control_enabled else "restore on unknown price",
                    now_ts,
                )
                print(f"[battery] restore -> ok={ok} reason={reason}", flush=True)
            else:
                print(f"[battery] alloc request ~{alloc_kw:.2f} kW (no control action)", flush=True)
            return

        if grid_cost <= 0.0:
            if state.get("active"):
                set_override_state(last_grid_price_eur_kwh=grid_cost)
                print(f"[battery] negative-price override active grid_cost={grid_cost:.4f}", flush=True)
                return
            if _retry_blocked(state, now_ts):
                print(f"[battery] negative-price override cooldown active until {state.get('next_retry_ts')}", flush=True)
                return
            ok, reason = self._activate_negative_price_control(grid_cost, now_ts)
            print(f"[battery] activate negative-price override -> ok={ok} reason={reason}", flush=True)
            return

        if state.get("active") or state.get("status") == "restore_failed":
            if state.get("status") == "restore_failed" and _retry_blocked(state, now_ts):
                print(f"[battery] restore cooldown active until {state.get('next_retry_ts')}", flush=True)
                return
            ok, reason = self._restore_targets(state.get("remembered") or {}, "price positive -> restore normal", now_ts)
            print(f"[battery] restore positive-price mode -> ok={ok} reason={reason}", flush=True)
            return

        if state.get("status") == "apply_failed" and not _retry_blocked(state, now_ts):
            clear_override_state()
        print(f"[battery] alloc request ~{alloc_kw:.2f} kW (no override needed)", flush=True)
