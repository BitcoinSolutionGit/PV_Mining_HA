# services/export_cap_boost.py
import time
from services.utils import load_state, update_state
from services.settings_store import get_var as set_get
from services.miners_store import list_miners, request_miner_state
from services.cooling_store import get_cooling

def _truthy(x, default=False):
    if x is None: return default
    s = str(x).strip().lower()
    if s in ("1","true","on","yes","y","enabled"): return True
    try: return float(s) > 0.0
    except: return False

def _auto_off_miners_sorted():
    """Auto+enabled, aktuell AUS; nach kleinster Leistung sortiert."""
    out = []
    for m in (list_miners() or []):
        if not _truthy(m.get("enabled"), True):  continue
        if str(m.get("mode","manual")).lower() != "auto":  continue
        if _truthy(m.get("effective_on", m.get("on")), False): continue
        p = float(m.get("power_kw") or 0.0)
        if p <= 0.0: continue
        # Cooling-Restriktion berücksichtigen
        if _truthy(m.get("require_cooling"), False):
            c = get_cooling() or {}
            ha = c.get("ha_on")
            cooling_ok = bool(c.get("effective_on")) if "effective_on" in c else (bool(ha) if ha is not None else _truthy(c.get("on"), False))
            if not cooling_ok: continue
        out.append((p, m))
    return [m for _, m in sorted(out, key=lambda x: x[0])]

def try_export_cap_boost(feed_kw: float, import_kw: float):
    """
    Wenn Einspeise-Kappe aktiv (~feed==cap), schalte vorsichtig einen kleinen Auto-Miner zu.
    Rolle zurück, wenn Import > (guard + 100 W).
    Merkt sich Zustand in load_state().
    """
    cap = float(set_get("grid_export_cap_kw", 0.0) or 0.0)
    if cap <= 0:  # aus
        def _clear(st: dict):
            st.pop("cap_boost", None)
        update_state(_clear)
        return None

    eps = 0.05  # kW Toleranz
    guard_w = float(set_get("surplus_guard_w", 100.0) or 100.0)
    cool_s  = int(set_get("boost_cooldown_s", 30) or 30)
    min_run = int(set_get("miner_min_run_s", 30) or 30)

    st = load_state()
    cb = st.get("cap_boost") or {}
    last_id = cb.get("last_id")
    since   = float(cb.get("since", 0))
    until   = float(cb.get("cooldown_until", 0))
    now     = time.time()

    # Sofort-Rollback falls Import zu hoch
    if import_kw * 1000.0 > guard_w + 100.0 and last_id:
        ok, reason = request_miner_state(last_id, False, now_ts=now, enforce_runtime=True)
        if ok:
            def _rollback(st2: dict):
                st2["cap_boost"] = {"last_id": None, "since": 0, "cooldown_until": now + cool_s}
            update_state(_rollback)
            return {"rollback": last_id}
        return {"rollback_blocked": last_id, "reason": reason}

    # Cooldown / Mindestlaufzeit respektieren
    if now < until or (last_id and now - since < min_run):
        return None

    # Nur boosten, wenn Kappe greift
    if feed_kw < cap - eps:
        def _inactive(st2: dict):
            st2["cap_boost"] = {"last_id": None, "since": 0, "cooldown_until": 0}
        update_state(_inactive)
        return None

    # Kleinsten geeigneten Auto-Miner wählen
    cand = next(iter(_auto_off_miners_sorted()), None)
    if not cand:
        return None

    ok, reason = request_miner_state(cand.get("id"), True, now_ts=now, enforce_runtime=True)
    if not ok:
        return {"probe_blocked": cand.get("id"), "reason": reason}

    def _probe_on(st2: dict):
        st2["cap_boost"] = {"last_id": cand.get("id"), "since": now, "cooldown_until": now + min_run}
    update_state(_probe_on)
    return {"probe_on": cand.get("id")}
