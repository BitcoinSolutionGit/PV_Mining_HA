# services/electricity_store.py
import os
from services.utils import load_yaml, save_yaml
from services.ha_sensors import get_sensor_value

CONFIG_DIR = "/config/pv_mining_addon"
ELEC_DEF = os.path.join(CONFIG_DIR, "electricity.yaml")
ELEC_OVR = os.path.join(CONFIG_DIR, "electricity.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

def _get_path(data: dict, path: str):
    cur = data or {}
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur

def _ensure_path(data: dict, path: str) -> dict:
    cur = data
    for k in path.split("."):
        cur = cur.setdefault(k, {})
    return cur

# ---------- mapping (Sensor-IDs) ----------
def resolve_sensor_id(kind: str) -> str:
    # 1/2: electricity.mapping (local > def)
    for path_file in (ELEC_OVR, ELEC_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "electricity.mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # 3: top-level mapping (legacy)
    for path_file in (ELEC_OVR, ELEC_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # 4: electricity-legacy
    if kind == "current_electricity_price":
        for key in ("electricity.price_sensor", "electricity.current_electricity_price"):
            for path_file in (ELEC_OVR, ELEC_DEF):
                v = _get_path(load_yaml(path_file, {}) or {}, key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    # 5: pv_mining_local_config.yaml (legacy)
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    fb = {"current_electricity_price": "sensor_current_electricity_price"}
    return (ents.get(fb.get(kind, ""), "") or "").strip()

def set_mapping(kind: str, sensor_id: str):
    ovr = load_yaml(ELEC_OVR, {}) or {}
    elec = ovr.setdefault("electricity", {})
    mapping = elec.setdefault("mapping", {})
    mapping[kind] = (sensor_id or "").strip()
    save_yaml(ELEC_OVR, ovr)

    if kind == "current_electricity_price":
        cfg = load_yaml(MAIN_CFG, {}) or {}
        cfg.setdefault("entities", {})
        cfg["entities"]["sensor_current_electricity_price"] = (sensor_id or "").strip()
        save_yaml(MAIN_CFG, cfg)

# ---------- variables (Zahlen/Modus/Währung) ----------
def get_var(key: str, default=None):
    v = _get_path(load_yaml(ELEC_OVR, {}) or {}, f"electricity.variables.{key}")
    if v is None:
        v = _get_path(load_yaml(ELEC_DEF, {}) or {}, f"electricity.variables.{key}")
    return default if v is None else v

def set_vars(**pairs):
    ovr = load_yaml(ELEC_OVR, {}) or {}
    vars_block = _ensure_path(ovr, "electricity.variables")
    for k, v in pairs.items():
        if v is not None:
            vars_block[k] = v
    save_yaml(ELEC_OVR, ovr)

# ---------- Logik: aktueller Preis + Formatierung ----------
def current_price() -> float | None:
    mode = str(get_var("pricing_mode", "") or "").lower()
    sensor_id = resolve_sensor_id("current_electricity_price")
    if mode not in ("fixed", "dynamic"):
        mode = "dynamic" if sensor_id else "fixed"
    if mode == "fixed":
        try:
            return float(get_var("fixed_price_value", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    if not sensor_id:
        return None
    try:
        return float(get_sensor_value(sensor_id))
    except (TypeError, ValueError):
        return None

def currency_symbol():
    c = str(get_var("currency", "EUR") or "EUR").upper()
    return "€" if c == "EUR" else c  # schlicht: EUR -> €, sonst ISO-Code

def price_color(v: float | None) -> str:
    if v is None:
        return "#888888"
    if v < 0.15:
        return "#27ae60"  # grün
    if v <= 0.25:
        return "#f1c40f"  # gelb
    return "#e74c3c"      # rot
