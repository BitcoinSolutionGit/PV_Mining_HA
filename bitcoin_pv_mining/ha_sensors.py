import os
import requests

def get_ha_token():
    return os.getenv("SUPERVISOR_TOKEN")

def get_sensor_value(entity_id):
    """Liefert aktuellen Wert eines Sensors."""
    token = get_ha_token()
    if not token:
        print("[ERROR] Kein Supervisor-Token verfügbar")
        return None

    url = f"http://supervisor/core/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            state = response.json().get("state")
            return float(state) if state not in (None, "unknown", "unavailable") else None
        print(f"[WARN] Fehler beim Abruf von {entity_id}: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Sensorwert {entity_id} nicht abrufbar:", e)

    return None

def list_all_sensors():
    """Gibt Liste aller Sensor-Entitäten zurück (für Dropdowns)."""
    token = get_ha_token()
    if not token:
        return []

    url = "http://supervisor/core/api/states"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return [
                s["entity_id"] for s in response.json()
                if s["entity_id"].startswith("sensor.")
            ]
    except Exception as e:
        print("[ERROR] Sensorliste konnte nicht geladen werden:", e)

    return []
