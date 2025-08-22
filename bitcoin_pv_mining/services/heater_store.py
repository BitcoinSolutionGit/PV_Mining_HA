from __future__ import annotations

import os

from typing import Any, Optional
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
HEAT_DEF   = os.path.join(CONFIG_DIR, "heater.yaml")
HEAT_OVR   = os.path.join(CONFIG_DIR, "heater.local.yaml")
MAIN_CFG   = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _get_path(d: dict, path: str, default=None):
    cur = d or {}
    for k in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur

def _ensure_path(d: dict, path: str) -> dict:
    cur = d
    for k in path.split("."):
        cur = cur.setdefault(k, {})
    return cur

def _as_bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on", "enabled")

def _as_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

# --------------------------------------------------------------------------------------
# Load / Save (override wins)
# --------------------------------------------------------------------------------------
def _load_all() -> dict:
    base = load_yaml(HEAT_DEF, {}) or {}
    ovr  = load_yaml(HEAT_OVR, {}) or {}

    out = {"heater": {"mapping": {}, "variables": {}}}
    out["heater"]["mapping"]   = {**(_get_path(base, "heater.mapping", {}) or {}), **(_get_path(ovr, "heater.mapping", {}) or {})}
    out["heater"]["variables"] = {**(_get_path(base, "heater.variables", {}) or {}), **(_get_path(ovr, "heater.variables", {}) or {})}
    return out

def _save_override(data: dict):
    # Wir schreiben NUR die Override-Datei (Defaults bleiben unangetastet)
    if not isinstance(data, dict):
        data = {}
    if "heater" not in data:
        data["heater"] = {"mapping": {}, "variables": {}}
    save_yaml(HEAT_OVR, data)

# --------------------------------------------------------------------------------------
# Mapping (input_number.*)
# --------------------------------------------------------------------------------------
def resolve_entity_id(kind: str) -> str:
    # 1) merged (ovr > def)
    merged = _load_all()
    val = (merged.get("heater", {}).get("mapping", {}) or {}).get(kind)
    if isinstance(val, str) and val.strip():
        return val.strip()

    # 2) LEGACY: top-level mapping (alt)
    for path_file in (HEAT_OVR, HEAT_DEF):
        legacy = _get_path(load_yaml(path_file, {}) or {}, "mapping", {})
        if isinstance(legacy, dict):
            v = legacy.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()

    # 3) OPTIONAL: Mirror im MAIN_CFG
    cfg  = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    # support underscore- UND dot-Keys
    fb = {
        "input_warmwasser_cache": ("input_number_warmwasser_cache", "input_number.warmwasser_cache"),
        "input_heizstab_cache":  ("input_number_heizstab_cache",  "input_number.heizstab_cache"),
    }
    for k in fb.get(kind, ()):
        v = ents.get(k, "")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""

def set_mapping(kind: str, entity_id: str) -> None:
    ovr = load_yaml(HEAT_OVR, {}) or {}
    mapping = _ensure_path(ovr, "heater.mapping")
    mapping[kind] = (entity_id or "").strip()
    _save_override(ovr)

    # Optionaler Mirror in MAIN_CFG (falls du das weiterverwenden willst)
    try:
        cfg = load_yaml(MAIN_CFG, {}) or {}
        ents = cfg.setdefault("entities", {})
        if kind == "input_warmwasser_cache":
            ents["input_number_warmwasser_cache"] = (entity_id or "").strip()
        elif kind == "input_heizstab_cache":
            ents["input_number_heizstab_cache"] = (entity_id or "").strip()
        save_yaml(MAIN_CFG, cfg)
    except Exception:
        pass

# --------------------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------------------
def get_var(name: str, default: Any = None) -> Any:
    """
    Liest eine Variable (override > default). Gibt default zurück, wenn nicht gefunden.
    """
    merged = _load_all()
    return (merged.get("heater", {}).get("variables", {}) or {}).get(name, default)

def set_vars(**changes) -> None:
    """
    Schreibt beliebige Variablen in heater.local.yaml (keine Whitelist).
    Typ-Sicherung für ein paar Schlüssel, damit UI/Engine konsistent bleiben.
    """
    ovr = load_yaml(HEAT_OVR, {}) or {}
    vars_block = _ensure_path(ovr, "heater.variables")

    for k, v in (changes or {}).items():
        if v is None:
            continue
        if k in ("enabled", "manual_override", "zero_export_kick_enabled"):
            vars_block[k] = _as_bool(v)
        elif k in ("wanted_water_temperature", "max_power_heater", "zero_export_kick_kw"):
            vars_block[k] = _as_float(v, 0.0)
        elif k in ("zero_export_kick_cooldown_s", "manual_override_percent"):
            try:
                vars_block[k] = int(v)
            except (TypeError, ValueError):
                vars_block[k] = 0
        else:
            vars_block[k] = v
    _save_override(ovr)

# Bequeme Typ-Wrapper für das UI / Planner
def is_enabled(default: bool = False) -> bool:
    return _as_bool(get_var("enabled", default), default)

def set_enabled(flag: bool) -> None:
    set_vars(enabled=bool(flag))
