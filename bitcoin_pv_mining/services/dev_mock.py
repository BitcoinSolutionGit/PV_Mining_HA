import os

from services.settings_store import get_var as set_get, set_vars as set_set
from services.battery_store import get_var as bat_get
from services.wallbox_store import get_var as wb_get
from services.heater_store import resolve_entity_id as heat_resolve
from services.utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
ELEC_DEF = os.path.join(CONFIG_DIR, "electricity.yaml")
ELEC_OVR = os.path.join(CONFIG_DIR, "electricity.local.yaml")

MOCK_ENABLED_KEY = "dev.mock_enabled"
MOCK_VALUES_KEY = "dev.mock_values"

DEV_PV_PRODUCTION = "mock:pv_production"
DEV_GRID_CONSUMPTION = "mock:grid_consumption"
DEV_GRID_FEED_IN = "mock:grid_feed_in"
DEV_ELECTRICITY_PRICE = "mock:electricity_price"
DEV_BATTERY_SOC = "mock:battery_soc"
DEV_BATTERY_VOLTAGE = "mock:battery_voltage"
DEV_BATTERY_CURRENT = "mock:battery_current"
DEV_BATTERY_POWER = "mock:battery_power"
DEV_BATTERY_TEMPERATURE = "mock:battery_temperature"
DEV_HEATER_WATER_TEMP = "mock:heater_water_temp"
DEV_HEATER_PERCENT = "mock:heater_percent"
DEV_WALLBOX_CONNECTED = "mock:wallbox_connected"
DEV_WALLBOX_POWER = "mock:wallbox_power"
DEV_WALLBOX_SESSION_ENERGY = "mock:wallbox_session_energy"
DEV_WALLBOX_READY = "mock:wallbox_ready"
VIRTUAL_BTC_PRICE = "mock:btc_price"
VIRTUAL_BTC_HASHRATE = "mock:btc_hashrate"


def _get_path(data: dict, path: str):
    cur = data or {}
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


def _parse_mock_value(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float, bool)):
        return raw

    s = str(raw).strip()
    if not s:
        return None

    low = s.lower()
    if low in ("on", "off", "true", "false", "unknown", "unavailable"):
        return low

    try:
        return float(s.replace(",", "."))
    except ValueError:
        return s


def is_enabled() -> bool:
    return bool(set_get(MOCK_ENABLED_KEY, False))


def get_values() -> dict:
    values = set_get(MOCK_VALUES_KEY, {})
    return values if isinstance(values, dict) else {}


def set_config(enabled: bool, values: dict):
    cleaned = {}
    for key, value in (values or {}).items():
        parsed = _parse_mock_value(value)
        if parsed is not None:
            cleaned[str(key)] = parsed
    set_set(**{MOCK_ENABLED_KEY: bool(enabled), MOCK_VALUES_KEY: cleaned})


def get_mock_sensor_value(entity_id: str):
    if not is_enabled() or not entity_id:
        return None
    return _parse_mock_value(get_values().get(entity_id))


def get_virtual_value(key: str, default=None):
    if not is_enabled():
        return default
    value = _parse_mock_value(get_values().get(key))
    return default if value is None else value


def effective_entity_key(entity_id: str | None, mock_key: str) -> str:
    entity_id = (entity_id or "").strip()
    if entity_id:
        return entity_id
    if is_enabled():
        return mock_key
    return entity_id


def _resolve_main_entity(key: str) -> str:
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    return (ents.get(key, "") or "").strip()


def _resolve_dashboard_sensor(kind: str) -> str:
    mapping_def = load_yaml(SENS_DEF, {}).get("mapping", {}) or {}
    mapping_ovr = load_yaml(SENS_OVR, {}).get("mapping", {}) or {}
    value = (mapping_ovr.get(kind) or mapping_def.get(kind) or "").strip()
    if value:
        return value

    legacy = {
        "pv_production": "sensor_pv_production",
        "grid_consumption": "sensor_grid_consumption",
        "grid_feed_in": "sensor_grid_feed_in",
    }
    return _resolve_main_entity(legacy.get(kind, ""))


def _resolve_electricity_sensor(kind: str) -> str:
    for path_file in (ELEC_OVR, ELEC_DEF):
        mapping = _get_path(load_yaml(path_file, {}) or {}, "electricity.mapping")
        if isinstance(mapping, dict):
            value = mapping.get(kind)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for path_file in (ELEC_OVR, ELEC_DEF):
        mapping = _get_path(load_yaml(path_file, {}) or {}, "mapping")
        if isinstance(mapping, dict):
            value = mapping.get(kind)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if kind == "current_electricity_price":
        return _resolve_main_entity("sensor_current_electricity_price")
    return ""


def _spec(label: str, key: str, mapped_entity: str = "", kind: str = "number", default: str = "") -> dict:
    return {
        "label": label,
        "key": key,
        "mapped_entity": mapped_entity,
        "kind": kind,
        "default": default,
    }


def collect_specs() -> list[dict]:
    return [
        _spec("PV production", DEV_PV_PRODUCTION, _resolve_dashboard_sensor("pv_production"), default="6.71"),
        _spec("Grid consumption", DEV_GRID_CONSUMPTION, _resolve_dashboard_sensor("grid_consumption"), default="0.09"),
        _spec("Grid feed-in", DEV_GRID_FEED_IN, _resolve_dashboard_sensor("grid_feed_in"), default="0.00"),
        _spec("Dynamic electricity price", DEV_ELECTRICITY_PRICE, _resolve_electricity_sensor("current_electricity_price"), default="0.18"),
        _spec("Battery SoC", DEV_BATTERY_SOC, bat_get("soc_entity", ""), default="72"),
        _spec("Battery voltage", DEV_BATTERY_VOLTAGE, bat_get("voltage_entity", ""), default="52.6"),
        _spec("Battery current", DEV_BATTERY_CURRENT, bat_get("current_entity", ""), default="-18.4"),
        _spec("Battery power", DEV_BATTERY_POWER, bat_get("power_entity", ""), default="-0.97"),
        _spec("Battery temperature", DEV_BATTERY_TEMPERATURE, bat_get("temperature_entity", ""), default="24.2"),
        _spec("Heater water temperature", DEV_HEATER_WATER_TEMP, heat_resolve("input_warmwasser_cache"), default="46.1"),
        _spec("Heater control percent", DEV_HEATER_PERCENT, heat_resolve("input_heizstab_cache"), default="38"),
        _spec("Wallbox connected", DEV_WALLBOX_CONNECTED, wb_get("connected_entity", ""), kind="text", default="on"),
        _spec("Wallbox power", DEV_WALLBOX_POWER, wb_get("power_entity", ""), default="4.20"),
        _spec("Wallbox session energy", DEV_WALLBOX_SESSION_ENERGY, wb_get("energy_session_entity", ""), default="8.60"),
        _spec("Wallbox ready", DEV_WALLBOX_READY, wb_get("ready_entity", ""), kind="text", default="on"),
        _spec("BTC price", VIRTUAL_BTC_PRICE, "pv_mining_local_config.entities.sensor_btc_price", default="68418.01"),
        _spec("BTC hashrate", VIRTUAL_BTC_HASHRATE, "pv_mining_local_config.entities.sensor_btc_hashrate", default="1030888481.22"),
    ]
