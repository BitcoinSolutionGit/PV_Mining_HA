# services/battery_store.py
import os, yaml
from services.utils import load_yaml  # dein bestehender Helper

CONFIG_DIR   = "/config/pv_mining_addon"
FILE_MAIN    = os.path.join(CONFIG_DIR, "battery.yaml")
FILE_LOCAL   = os.path.join(CONFIG_DIR, "battery.local.yaml")
FILE_LEGACY  = os.path.join(CONFIG_DIR, "battery_store.yaml")  # optionaler Fallback

DEFAULTS = {
    "enabled": False,
    "mode": "manual",              # "manual" | "auto"

    # Limits/Kapazität
    "capacity_kwh": 11.0,
    "max_charge_kw": 3.0,
    "max_discharge_kw": 3.0,

    # Sensor-Auswahl (nur Strings; können leer sein)
    "capacity_entity": "",         # optional: sensor für Kapazität (kWh)
    "soc_entity": "",              # % SoC
    "voltage_entity": "",          # V (DC)
    "current_entity": "",          # A (DC; +laden / -entladen)
    "temperature_entity": "",      # °C

    # Ziele/Policies
    "target_soc": 90.0,
    "reserve_soc": 20.0,
    "allow_grid_charge": False,
}

def _load_all() -> dict:
    # Reihenfolge: DEFAULTS < battery.yaml < battery.local.yaml < legacy
    data = DEFAULTS.copy()
    data.update(load_yaml(FILE_MAIN,  {}))
    data.update(load_yaml(FILE_LOCAL, {}))
    # Nur falls vorhanden: alte Datei als höchste Priorität mergen
    if os.path.exists(FILE_LEGACY):
        try:
            with open(FILE_LEGACY, "r", encoding="utf-8") as f:
                data.update(yaml.safe_load(f) or {})
        except Exception:
            pass
    return data

def _save_local(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(FILE_LOCAL, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, allow_unicode=True)

def get_var(key: str, default=None):
    return _load_all().get(key, DEFAULTS.get(key, default))

def set_vars(**kwargs):
    # Wir schreiben ausschließlich in battery.local.yaml (Basis-Datei bleibt unangetastet)
    current = load_yaml(FILE_LOCAL, {})
    for k, v in kwargs.items():
        if v is not None:
            current[k] = v
    _save_local(current)
    # Rückgabe = gemergter Endstand (für UI direkt verwendbar)
    merged = _load_all()
    merged.update(current)
    return merged
