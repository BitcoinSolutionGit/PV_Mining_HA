# services/ha_entities.py
import os, requests
from services.ha_sensors import list_entities_by_domain

_HA = "http://supervisor/core/api"
_HDR = {"Authorization": f"Bearer {os.getenv('SUPERVISOR_TOKEN')}",
        "Content-Type": "application/json"}

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

def call_action(entity_id: str, turn_on: bool = True) -> bool:
    """Ruft den passenden HA-Service für switch/script/… auf."""
    if not entity_id:
        return False
    domain = entity_id.split(".", 1)[0]
    # Service-Mapping
    if domain == "script":
        svc = "script/turn_on"  # scripts haben nur turn_on
    elif domain in ("switch", "input_boolean", "light"):
        svc = f"{domain}/{'turn_on' if turn_on else 'turn_off'}"
    elif domain == "button":
        svc = "button/press"
    else:
        # generisch versuchen
        svc = f"homeassistant/{'turn_on' if turn_on else 'turn_off'}"

    url = f"{_HA}/services/{svc}"
    try:
        r = requests.post(url, headers=_HDR, json={"entity_id": entity_id}, timeout=5)
        return r.status_code in (200, 201)
    except Exception:
        return False

def get_entity_state(entity_id: str):
    """Rohzustand der Entity (string)."""
    if not entity_id:
        return None
    try:
        r = requests.get(f"{_HA}/states/{entity_id}", headers=_HDR, timeout=5)
        if r.status_code == 200:
            return (r.json() or {}).get("state")
    except Exception:
        pass
    return None

def is_on_like(state) -> bool:
    """'on'-Logik für bool/switch/sensor (Zahlen > 0)."""
    if state is None:
        return False
    s = str(state).strip().lower()
    if s in ("on", "true", "open", "home", "heat", "cool"):
        return True
    try:
        return float(s) > 0.0
    except Exception:
        return False

# ganz unten o. unter list_entities(...)
def list_ready_entities(domains: tuple[str, ...] = ("input_boolean",)) -> list[str]:
    """Entities für den Cooling-Ready-Dropdown (Standard: nur input_boolean)."""
    return list_entities(domains=domains)



