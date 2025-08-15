# services/wallbox_store.py
import os, yaml

CONFIG_DIR = "/config/pv_mining_addon"
FILE = os.path.join(CONFIG_DIR, "wallbox_store.yaml")

DEFAULTS = {
    "enabled": False,
    "mode": "manual",              # "manual" | "auto"
    "max_charge_kw": 11.0,         # 11kW oder 22kW
    "phases": 3,                   # 1 oder 3
    "max_current_a": 16,           # 16A bei 11kW; 32A bei 22kW

    # Entities
    "connected_entity": "",        # bool: EV connected?
    "power_entity": "",            # kW: aktuelle Ladeleistung
    "energy_session_entity": "",   # kWh: geladene Energie aktuelle Session
    "ready_entity": "",            # bool: True = charging/running

    # Actions
    "action_on_entity": "",        # start charging
    "action_off_entity": "",       # stop charging

    # Targets & Policy
    "target_energy_kwh": 10.0,     # Wunschladung für Session (optional)
    "solar_only": True,            # nur PV-Überschuss laden (Auto)
    "min_surplus_kw": 1.0,         # Mindest-Überschuss zum Start (Auto)
}

def _load():
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    out = DEFAULTS.copy()
    out.update(data)
    return out

def _save(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, allow_unicode=True)

def get_var(key: str, default=None):
    return _load().get(key, DEFAULTS.get(key, default))

def set_vars(**kwargs):
    data = _load()
    for k, v in kwargs.items():
        if v is not None:
            data[k] = v
    _save(data)
    return data
