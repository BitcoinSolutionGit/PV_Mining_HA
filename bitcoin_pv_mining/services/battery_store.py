# services/battery_store.py
import os, yaml

CONFIG_DIR = "/config/pv_mining_addon"
FILE = os.path.join(CONFIG_DIR, "battery_store.yaml")

DEFAULTS = {
    "enabled": False,
    "mode": "manual",              # "manual" | "auto"
    "capacity_kwh": 11.0,          # BYD ~11 kWh
    "max_charge_kw": 3.0,
    "max_discharge_kw": 3.0,

    # Entities (Strings; dürfen leer sein, dann werden KPIs geschätzt)
    "soc_entity": "",              # z.B. sensor.fronius_battery_soc (%)
    "power_entity": "",            # z.B. sensor.battery_power (kW, +laden/-entladen)
    "ready_entity": "",            # bool: True = charging/running

    # Actions (Switch/Script) – optional
    "action_on_entity": "",        # force charge / enable charging
    "action_off_entity": "",       # stop charge / disable charging

    # Targets/Policies
    "target_soc": 90.0,            # %
    "reserve_soc": 20.0,           # % (für Notstrom/Reserve)
    "allow_grid_charge": False,    # nur Auto-Logik später relevant
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
