# services/ha_sensors.py
import os
import requests
from .utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"

def get_ha_token():
    return os.getenv("SUPERVISOR_TOKEN")

def get_sensor_value(entity_id):
    """Liefert aktuellen Wert eines Sensors aus Home Assistant."""
    token = get_ha_token()
    if not token or not entity_id:
        return None

    url = f"http://supervisor/core/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            state = r.json().get("state")
            try:
                return float(state)
            except (TypeError, ValueError):
                return None
        else:
            print(f"[WARN] Error fetching {entity_id}: {r.status_code}")
    except Exception as e:
        print(f"[ERROR] sensor value {entity_id} unfetchable:", e)
    return None

def _fallback_sensor_candidates():
    """Dev-Fallback: sammelt Kandidaten aus lokalen YAML-Mappings (ohne HA)."""
    sensors = []
    for fname in ("sensors.local.yaml", "sensors.yaml"):
        data = load_yaml(os.path.join(CONFIG_DIR, fname), {})
        if isinstance(data, dict):
            mapping = data.get("mapping", {})
            if isinstance(mapping, dict):
                for v in mapping.values():
                    if isinstance(v, str) and v:
                        sensors.append(v)
    # eindeutige, sortierte Liste zurückgeben
    return sorted(set(sensors))

def list_all_sensors():
    """Gibt Liste aller Sensor-entity_ids zurück.
    - Mit HA-Token: echte Liste aus Home Assistant
    - Ohne Token: Fallback aus YAML-Mappings (Dev-Mode / PyCharm)
    """
    token = get_ha_token()
    if not token:
        return _fallback_sensor_candidates()

    url = "http://supervisor/core/api/states"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            return [
                e["entity_id"]
                for e in r.json()
                if isinstance(e, dict) and str(e.get("entity_id", "")).startswith("sensor.")
            ]
        else:
            print(f"[WARN] HA API Error: {r.status_code}; using fallback.")
            return _fallback_sensor_candidates()
    except Exception as e:
        print(f"[ERROR] sensor list unreadable: {e}; using fallback.")
        return _fallback_sensor_candidates()
