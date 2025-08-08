# utils_config.py
import os, json, yaml, uuid, datetime as dt

CONFIG_DIR = "/config/pv_mining_addon"
SENSORS_PATH = os.path.join(CONFIG_DIR, "sensors.yaml")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")

def load_yaml(path: str, default=None):
    """Lädt YAML und gibt default zurück, falls nicht vorhanden."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except Exception:
        return default

def save_yaml(path, data):
    """
    Speichert ein Python-Objekt (z.B. dict) als YAML.
    Erstellt Ordner bei Bedarf automatisch.
    """
    import os
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"[ERROR] Could not save YAML to {path}: {e}")

def load_sensors():
    return load_yaml(SENSORS_PATH, {"entities": {}})

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        st = {
            "install_id": str(uuid.uuid4()),
            "sponsor_token": "",
            "premium_enabled": False,
            "lease_expires_at": None,
            "last_heartbeat_at": None
        }
        save_state(st)
        return st

def save_state(st):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def iso_now():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
