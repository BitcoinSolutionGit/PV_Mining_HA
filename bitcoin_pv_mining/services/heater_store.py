# services/heater_store.py
import os
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
HEAT_DEF = os.path.join(CONFIG_DIR, "heater.yaml")
HEAT_OVR = os.path.join(CONFIG_DIR, "heater.local.yaml")
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

# ---------- mapping (nun: input_numbers) ----------
def resolve_entity_id(kind: str) -> str:
    # heater.mapping (local > default)
    for path_file in (HEAT_OVR, HEAT_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "heater.mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # Legacy top-level mapping (optional)
    for path_file in (HEAT_OVR, HEAT_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # MAIN_CFG-Fallback (optional)
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    fb = {
        "input_warmwasser_cache": "input_number_warmwasser_cache",
        "input_heizstab_cache":  "input_number_heizstab_cache",
    }
    return (ents.get(fb.get(kind, ""), "") or "").strip()

def set_mapping(kind: str, entity_id: str):
    ovr = load_yaml(HEAT_OVR, {}) or {}
    heater = ovr.setdefault("heater", {})
    mapping = heater.setdefault("mapping", {})
    mapping[kind] = (entity_id or "").strip()
    save_yaml(HEAT_OVR, ovr)

    # optionaler Mirror in MAIN_CFG
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.setdefault("entities", {})
    if kind == "input_warmwasser_cache":
        ents["input_number_warmwasser_cache"] = (entity_id or "").strip()
    if kind == "input_heizstab_cache":
        ents["input_number_heizstab_cache"] = (entity_id or "").strip()
    save_yaml(MAIN_CFG, cfg)

# ---------- variables (ohne Cache-Felder) ----------
def get_var(key: str, default=None):
    v = _get_path(load_yaml(HEAT_OVR, {}) or {}, f"heater.variables.{key}")
    if v is None:
        v = _get_path(load_yaml(HEAT_DEF, {}) or {}, f"heater.variables.{key}")
    return default if v is None else v

def set_vars(**pairs):
    ovr = load_yaml(HEAT_OVR, {}) or {}
    vars_block = _ensure_path(ovr, "heater.variables")
    for k, v in pairs.items():
        if v is not None:
            vars_block[k] = v
    save_yaml(HEAT_OVR, ovr)
