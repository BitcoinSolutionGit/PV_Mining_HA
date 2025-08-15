# services/ha_entities.py
import os, requests

def _ha_headers():
    token = os.getenv("SUPERVISOR_TOKEN") or ""
    return {"Authorization": f"Bearer {token}"}

def _ha_get_states():
    try:
        r = requests.get("http://supervisor/core/api/states", headers=_ha_headers(), timeout=5)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []

def list_entities(domains=("script", "switch")) -> list[str]:
    """Return entity_ids for the given HA domains (e.g., 'script', 'switch')."""
    states = _ha_get_states()
    wanted = set(str(d).lower() for d in (domains or []))
    out = []
    for st in states:
        ent = st.get("entity_id", "")
        if not ent or "." not in ent:
            continue
        dom = ent.split(".", 1)[0].lower()
        if dom in wanted:
            out.append(ent)
    return sorted(out)

def list_actions() -> list[dict]:
    """
    Return dropdown options for scripts & switches:
    [{'label': 'Script • My Script (script.my_script)', 'value': 'script.my_script'}, ...]
    """
    opts = []
    for ent in list_entities(("script", "switch")):
        dom, _ = ent.split(".", 1)
        label_prefix = "Script" if dom == "script" else "Switch"
        opts.append({"label": f"{label_prefix} • {ent}", "value": ent})
    return opts
