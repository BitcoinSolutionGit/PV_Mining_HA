import os

from services.utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

LEGACY_ENTITY_KEYS = {
    "pv_production": "sensor_pv_production",
    "grid_consumption": "sensor_grid_consumption",
    "grid_feed_in": "sensor_grid_feed_in",
    "pv_surplus": "sensor_pv_surplus",
    "house_load": "sensor_house_load",
    "house_consumption": "sensor_house_consumption",
    "home_consumption": "sensor_home_consumption",
}

try:
    from services.dev_mock import (
        effective_entity_key,
        DEV_PV_PRODUCTION,
        DEV_GRID_CONSUMPTION,
        DEV_GRID_FEED_IN,
    )
except Exception:
    def effective_entity_key(entity_id, _mock_key):
        return (entity_id or "").strip()

    DEV_PV_PRODUCTION = "mock:pv_production"
    DEV_GRID_CONSUMPTION = "mock:grid_consumption"
    DEV_GRID_FEED_IN = "mock:grid_feed_in"

MOCK_ENTITY_KEYS = {
    "pv_production": DEV_PV_PRODUCTION,
    "grid_consumption": DEV_GRID_CONSUMPTION,
    "grid_feed_in": DEV_GRID_FEED_IN,
}


def _mapping_value(path: str, key: str) -> str:
    mapping = (load_yaml(path, {}).get("mapping", {}) or {})
    return (mapping.get(key) or "").strip()


def _legacy_value(key: str) -> str:
    legacy_key = LEGACY_ENTITY_KEYS.get(key, "")
    if not legacy_key:
        return ""
    cfg = load_yaml(MAIN_CFG, {}) or {}
    entities = cfg.get("entities", {}) or {}
    return (entities.get(legacy_key) or "").strip()


def resolve_sensor_id(kind: str, *, allow_mock: bool = True) -> str:
    real = _mapping_value(SENS_OVR, kind) or _mapping_value(SENS_DEF, kind) or _legacy_value(kind)
    if allow_mock:
        fallback = MOCK_ENTITY_KEYS.get(kind, "")
        if fallback:
            return effective_entity_key(real, fallback)
    return real

