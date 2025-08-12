import os
from dash import html, dcc
from dash.dependencies import Input, Output, State
from services.ha_sensors import list_all_sensors
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
ELEC_DEF = os.path.join(CONFIG_DIR, "electricity.yaml")
ELEC_OVR = os.path.join(CONFIG_DIR, "electricity.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

# Gleiche Funktion wie im Dashboard
def resolve_sensor_id(kind: str) -> str:
    """
    kind ∈ {"pv_production","load_consumption","grid_feed_in"}
    """
    mapping_def = load_yaml(ELEC_DEF, {}).get("mapping", {})
    mapping_ovr = load_yaml(ELEC_OVR, {}).get("mapping", {})

    sid = (mapping_ovr.get(kind) or mapping_def.get(kind) or "").strip()
    if sid:
        return sid

    cfg = load_yaml(MAIN_CFG, {})
    ents = cfg.get("entities", {})
    fallback_keys = {
        "current_electricity_price": "sensor_current_electricity_price",
    }
    return (ents.get(fallback_keys[kind], "") or "").strip()

def layout():
    # Dropdown-Optionen laden
    sensor_options = [{"label": s, "value": s} for s in list_all_sensors()]

    return html.Div([
        html.H2("Configure your electricity values"),

        html.Label("current electricity price"),
        dcc.Dropdown(
            id="sensor-current-electricity-price",
            options=sensor_options,
            value=resolve_sensor_id("current_electricity_price"),
            placeholder="Select sensor..."
        ),

        html.Button("Save", id="save-electricity", style={"marginTop": "20px"}),
        html.Div(id="save-electricity-status", style={"marginTop": "10px", "color": "green"})
    ])


def register_callbacks(app):
    @app.callback(
        Output("save-electricity-status", "children"),
        Input("save-electricity", "n_clicks"),
        State("sensor-current-electricity-price", "value")
    )
    def save_mapping(n_clicks, pv, load, feed):
        if not n_clicks:
            return ""

        mapping = {
            "current_electricity_price": pv or ""
        }

        # In sensors.local.yaml schreiben
        save_yaml(ELEC_OVR, {"mapping": mapping})

        # Spiegelung in alte Config für Rückwärtskompatibilität
        cfg = load_yaml(MAIN_CFG, {})
        cfg.setdefault("entities", {})
        cfg["entities"]["sensor_current_electricity_price"] = pv or ""
        save_yaml(MAIN_CFG, cfg)

        return "Electricity settings saved!"
