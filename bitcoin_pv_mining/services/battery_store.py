# services/battery_store.py
import os, yaml
from .utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
BASE_FILE  = os.path.join(CONFIG_DIR, "battery.yaml")
LOCAL_FILE = os.path.join(CONFIG_DIR, "battery.local.yaml")
RUNTIME_FILE = os.path.join(CONFIG_DIR, "battery.runtime.yaml")

DEFAULTS = {
    "enabled": False,
    "capacity_kwh": 11.0,
    "max_charge_kw": 3.0,
    "max_discharge_kw": 3.0,

    # Sensor-Entities (optional)
    "capacity_entity": "",
    "soc_entity": "",
    "power_entity": "",
    "voltage_entity": "",
    "current_entity": "",
    "temperature_entity": "",

    # Ziele/Policies
    "target_soc": 90.0,
    "reserve_soc": 20.0,
    "allow_grid_charge": False,

    # Negative-price control via Home Assistant entities
    "neg_price_control_enabled": False,
    "discharge_limit_entity": "",
    "discharge_limit_negative_w": 0.0,
    "discharge_limit_normal_w": None,
    "charge_allowed_entity": "",
    "charge_allowed_on_entity": "",
    "charge_allowed_off_entity": "",
    "charge_power_entity": "",
    "charge_power_negative_w": None,
    "charge_power_normal_w": None,
    "target_soc_entity": "",
    "target_soc_negative_pct": 100.0,
    "target_soc_normal_pct": None,
}

RUNTIME_DEFAULTS = {
    "active": False,
    "status": "idle",
    "error": "",
    "activated_at": 0.0,
    "last_action_at": 0.0,
    "next_retry_ts": 0.0,
    "last_grid_price_eur_kwh": None,
    "remembered": {},
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
        if k in DEFAULTS:   # nur bekannte Keys zulassen
            cur[k] = v
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(cur, f, sort_keys=True, allow_unicode=True)
    return _merged()


def get_override_state() -> dict:
    cur = load_yaml(RUNTIME_FILE, {}) or {}
    out = dict(RUNTIME_DEFAULTS)
    if isinstance(cur, dict):
        out.update(cur)
    remembered = out.get("remembered")
    out["remembered"] = remembered if isinstance(remembered, dict) else {}
    return out


def set_override_state(**kwargs) -> dict:
    cur = get_override_state()
    for k, v in kwargs.items():
        if k in RUNTIME_DEFAULTS:
            cur[k] = v
    save_yaml(RUNTIME_FILE, cur)
    return cur


def clear_override_state() -> dict:
    save_yaml(RUNTIME_FILE, dict(RUNTIME_DEFAULTS))
    return dict(RUNTIME_DEFAULTS)
