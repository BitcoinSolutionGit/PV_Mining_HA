# services/ha_entities.py
import os, time, requests
from services.ha_sensors import list_entities_by_domain

import os, time, requests
from services.ha_sensors import list_entities_by_domain  # falls genutzt

def _ha_base_and_headers():
    """
    Bevorzugt Supervisor-Proxy (Add-on). Fällt sonst auf HASS_URL + Token zurück.
    Env lokal:
      HASS_URL = http://homeassistant.local:8123
      HASS_TOKEN oder LONG_LIVED_TOKEN = <LLAT>
    """
    sup = os.getenv("SUPERVISOR_TOKEN")
    if sup:
        return "http://supervisor/core/api", {
            "Authorization": f"Bearer {sup}",
            "Content-Type": "application/json",
        }
    url = (os.getenv("HASS_URL") or os.getenv("HOME_ASSISTANT_URL") or "").rstrip("/")
    token = os.getenv("HASS_TOKEN") or os.getenv("LONG_LIVED_TOKEN") or ""
    if url and token:
        return f"{url}/api", {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    # Fallback – ohne Basis/Token werden Calls scheitern, wir loggen dann im _post_service.
    return "", {"Content-Type": "application/json"}

def _post_service(domain: str, service: str, payload: dict) -> bool:
    base, headers = _ha_base_and_headers()
    url = f"{base}/services/{domain}/{service}".replace("//services", "/services")
    try:
        r = requests.post(url, headers=headers, json=payload or {}, timeout=8)
        ok = 200 <= r.status_code < 300
        if not ok:
            print(f"[ha_entities] {domain}.{service} -> {r.status_code}: {r.text[:300]}", flush=True)
        return ok
    except Exception as e:
        print(f"[ha_entities] {domain}.{service} EXC: {e}", flush=True)
        return False


def _ha_get_states():
    base, headers = _ha_base_and_headers()
    try:
        r = requests.get(f"{base}/states", headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json() or []
        print(f"[ha_entities] GET /states -> {r.status_code}: {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"[ha_entities] GET /states EXC: {e}", flush=True)
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
    """
    Führt die passende Aktion für Scripts/Switches/Input-Boolean (& Button) aus.
    - script.X:      script.turn_on (OFF gibt es als Script; hier immer turn_on)
    - switch.X:      switch.turn_on/off
    - input_boolean: input_boolean.turn_on/off
    - button.X:      button.press
    - sonst:         homeassistant.turn_on/off
    """
    if not entity_id or "." not in entity_id:
        print("[ha_entities] call_action: invalid entity_id", flush=True)
        return False

    domain = entity_id.split(".", 1)[0].lower()
    payload = {"entity_id": entity_id}

    if domain == "script":
        ok = _post_service("script", "turn_on", payload)
    elif domain == "switch":
        ok = _post_service("switch", "turn_on" if turn_on else "turn_off", payload)
    elif domain == "input_boolean":
        ok = _post_service("input_boolean", "turn_on" if turn_on else "turn_off", payload)
    elif domain == "button":
        ok = _post_service("button", "press", payload)
    else:
        ok = _post_service("homeassistant", "turn_on" if turn_on else "turn_off", payload)

    time.sleep(0.15)  # kleine Entzerrung für Sequenzen
    return ok


def get_entity_state(entity_id: str):
    """Rohzustand der Entity (string)."""
    if not entity_id:
        return None
    base, headers = _ha_base_and_headers()
    try:
        r = requests.get(f"{base}/states/{entity_id}", headers=headers, timeout=8)
        if r.status_code == 200:
            return (r.json() or {}).get("state")
        print(f"[ha_entities] GET /states/{entity_id} -> {r.status_code}: {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"[ha_entities] GET state EXC: {e}", flush=True)
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



