# services/battery_store.py
import os, yaml
from .utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
BASE_FILE  = os.path.join(CONFIG_DIR, "battery.yaml")
LOCAL_FILE = os.path.join(CONFIG_DIR, "battery.local.yaml")

DEFAULTS = {
    "enabled": False,
    "mode": "manual",          # manual | auto
    "capacity_kwh": 11.0,
    "max_charge_kw": 3.0,
    "max_discharge_kw": 3.0,

    # Sensor-Entities (optional)
    "capacity_entity": "",
    "soc_entity": "",
    "voltage_entity": "",
    "current_entity": "",
    "temperature_entity": "",

    # Ziele/Policies
    "target_soc": 90.0,
    "reserve_soc": 20.0,
    "allow_grid_charge": False,
}

def _merged():
    data = DEFAULTS.copy()
    data.update(load_yaml(BASE_FILE, {}) or {})
    data.update(load_yaml(LOCAL_FILE, {}) or {})
    return data

def get_var(key: str, default=None):
    return _merged().get(key, DEFAULTS.get(key, default))

def set_vars(**kwargs):
    # nur in battery.local.yaml schreiben
    cur = load_yaml(LOCAL_FILE, {}) or {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in DEFAULTS:   # nur bekannte Keys zulassen
            cur[k] = v
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(cur, f, sort_keys=True, allow_unicode=True)
    return _merged()
