import os
from dash import html, dcc
from dash.dependencies import Input, Output, State
from services.ha_sensors import list_all_sensors
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

# Gleiche Funktion wie im Dashboard
def resolve_sensor_id(kind: str) -> str:
    """
    kind ∈ {"pv_production","load_consumption","grid_feed_in"}
    """
    mapping_def = load_yaml(SENS_DEF, {}).get("mapping", {})
    mapping_ovr = load_yaml(SENS_OVR, {}).get("mapping", {})

    sid = (mapping_ovr.get(kind) or mapping_def.get(kind) or "").strip()
    if sid:
        return sid

    cfg = load_yaml(MAIN_CFG, {})
    ents = cfg.get("entities", {})
    fallback_keys = {
        "pv_production": "sensor_pv_production",
        "load_consumption": "sensor_load_consumption",
        "grid_feed_in": "sensor_grid_feed_in",
    }
    return (ents.get(fallback_keys[kind], "") or "").strip()


def layout():
    # Dropdown-Optionen laden
    sensor_options = [{"label": s, "value": s} for s in list_all_sensors()]

    return html.Div([
        html.H2("Select your HA Sensors"),

        html.Label("PV production"),
        dcc.Dropdown(
            id="sensor-pv-production",
            options=sensor_options,
            value=resolve_sensor_id("pv_production"),
            placeholder="Select sensor..."
        ),

        html.Label("Load consumption", style={"marginTop": "15px"}),
        dcc.Dropdown(
            id="sensor-load-consumption",
            options=sensor_options,
            value=resolve_sensor_id("load_consumption"),
            placeholder="Select sensor..."
        ),

        html.Label("Grid feed-in", style={"marginTop": "15px"}),
        dcc.Dropdown(
            id="sensor-grid-feed-in",
            options=sensor_options,
            value=resolve_sensor_id("grid_feed_in"),
            placeholder="Select sensor..."
        ),

        html.Button("Save", id="save-sensors", style={"marginTop": "20px"}),
        html.Div(id="save-sensors-status", style={"marginTop": "10px", "color": "green"})
    ])


def register_callbacks(app):
    @app.callback(
        Output("save-sensors-status", "children"),
        Input("save-sensors", "n_clicks"),
        State("sensor-pv-production", "value"),
        State("sensor-load-consumption", "value"),
        State("sensor-grid-feed-in", "value")
    )
    def save_mapping(n_clicks, pv, load, feed):
        if not n_clicks:
            return ""

        mapping = {
            "pv_production": pv or "",
            "load_consumption": load or "",
            "grid_feed_in": feed or ""
        }

        # In sensors.local.yaml schreiben
        save_yaml(SENS_OVR, {"mapping": mapping})

        # Spiegelung in alte Config für Rückwärtskompatibilität
        cfg = load_yaml(MAIN_CFG, {})
        cfg.setdefault("entities", {})
        cfg["entities"]["sensor_pv_production"] = pv or ""
        cfg["entities"]["sensor_load_consumption"] = load or ""
        cfg["entities"]["sensor_grid_feed_in"] = feed or ""
        save_yaml(MAIN_CFG, cfg)

        return "Sensors saved!"
