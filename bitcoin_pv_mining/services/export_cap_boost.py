# services/export_cap_boost.py
import time
from services.utils import load_state, save_state
from services.settings_store import get_var as set_get
from services.miners_store import list_miners, update_miner
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
        if _truthy(m.get("on"), False):          continue
        p = float(m.get("power_kw") or 0.0)
        if p <= 0.0: continue
        # Cooling-Restriktion berücksichtigen
        if _truthy(m.get("require_cooling"), False):
            c = get_cooling() or {}
            ha = c.get("ha_on")
            cooling_ok = (bool(ha) if ha is not None else _truthy(c.get("on"), False))
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
        st = load_state(); st.pop("cap_boost", None); save_state(st); return None

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
        update_miner(last_id, on=False)
        st["cap_boost"] = {"last_id": None, "since": 0, "cooldown_until": now + cool_s}
        save_state(st)
        return {"rollback": last_id}

    # Cooldown / Mindestlaufzeit respektieren
    if now < until or (last_id and now - since < min_run):
        return None

    # Nur boosten, wenn Kappe greift
    if feed_kw < cap - eps:
        st["cap_boost"] = {"last_id": None, "since": 0, "cooldown_until": 0}
        save_state(st)
        return None

    # Kleinsten geeigneten Auto-Miner wählen
    cand = next(iter(_auto_off_miners_sorted()), None)
    if not cand:
        return None

    update_miner(cand.get("id"), on=True)  # Miner einschalten (dein Consumer kümmert sich um HA-Action)
    st["cap_boost"] = {"last_id": cand.get("id"), "since": now, "cooldown_until": now + min_run}
    save_state(st)
    return {"probe_on": cand.get("id")}
