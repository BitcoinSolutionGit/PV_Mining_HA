# services/battery_store.py
import os, yaml

CONFIG_DIR = "/config/pv_mining_addon"
FILE = os.path.join(CONFIG_DIR, "battery_store.yaml")

DEFAULTS = {
    "enabled": False,
    "mode": "manual",              # "manual" | "auto"
    "capacity_entity": "",


    # Sensor-Entities (alles optional; Strings)
    "soc_entity": "",            # z.B. sensor.fronius_battery_soc  (%)
    "dc_voltage_entity": "",     # z.B. sensor.battery_dc_voltage   (V)
    "dc_current_entity": "",     # z.B. sensor.battery_dc_current   (A; + = Laden)
    "temperature_entity": "",    # z.B. sensor.battery_temp         (°C, optional)

    # (Alt-/Kompatibilität: wird nicht mehr benutzt, darf in YAML stehen)
    "power_entity": "",          # früherer kW-Sensor (optional/legacy)

    # Ziele/Policies
    "target_soc": 90.0,          # %
    "reserve_soc": 20.0,         # %
    "allow_grid_charge": False,
}

def _load():
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    out = DEFAULTS.copy()
    out.update(data or {})
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
