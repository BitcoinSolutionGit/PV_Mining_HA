import yaml
import os
import requests
from dash import html, dcc, Input, Output, State
import dash
from ha_sensors import list_all_sensors

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = "/config/pv_mining_addon/pv_mining_local_config.yaml"

def recreate_config_file():
    default_content = """
feature_flags:
  heater_active: false
  wallbox_active: false
  battery_active: false
entities:
  sensor_pv_production: ""
  sensor_load_consumption: ""
"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            f.write(default_content)
        print("[INFO] Config manually recreated.")
        return True
    except Exception as e:
        print(f"[ERROR] Manual config recreation failed: {e}")
        return False

def load_entities():
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f).get("entities", {})
    except:
        return {}

def save_entities(data):
    try:
        with open(CONFIG_PATH, "r") as f:
            full_config = yaml.safe_load(f)
        full_config["entities"] = data
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(full_config, f)
    except Exception as e:
        print("[ERROR] Saving entities failed:", e)

def fetch_sensors_from_homeassistant():
    """Liefert eine Liste aller sensor-Entitäten aus HA"""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        print("[WARN] No Supervisor token available.")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        res = requests.get("http://supervisor/core/api/states", headers=headers, timeout=5)
        if res.status_code == 200:
            sensors = [e["entity_id"] for e in res.json() if e["entity_id"].startswith("sensor.")]
            return [{"label": s, "value": s} for s in sensors]
        else:
            print(f"[WARN] HA API Error: {res.status_code}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch sensors: {e}")
    return []


def generate_settings_layout():
    current = load_entities()
    sensor_options = fetch_sensors_from_homeassistant()

    return html.Div([
        html.H2("select sensors"),

        html.Label("PV-production sensor"),
        dcc.Dropdown(
            id="sensor-pv-production",
            options=sensor_options,
            value=current.get("sensor_pv_production", ""),
            placeholder="select sensor...",
            style={"width": "100%", "color": "blue"}
        ),

        html.Label("Load-consumption sensor", style={"marginTop": "15px"}),
        dcc.Dropdown(
            id="sensor-load-consumption",
            options=sensor_options,
            value=current.get("sensor_load_consumption", ""),
            placeholder="select sensor...",
            style={"width": "100%", "color": "blue"}
        ),

        html.Button("Save", id="save-entities", style={"marginTop": "20px"}),
        html.Div(id="save-status", style={"marginTop": "10px", "color": "green"}),

        html.Button("recreate local config", id="rebuild-config",
                    style={"marginTop": "20px", "backgroundColor": "red", "color": "white"}),
        html.Div(id="rebuild-config-status", style={"marginTop": "10px", "color": "green"})

    ])

def register_settings_callbacks(app):
    @app.callback(
        Output("sensor-pv-production", "style"),
        Output("sensor-load-consumption", "style"),
        Output("save-status", "children"),
        Input("save-entities", "n_clicks"),
        State("sensor-pv-production", "value"),
        State("sensor-load-consumption", "value")
    )
    def save_inputs(n_clicks, pv_production, load_consumption):
        if n_clicks is None:
            raise dash.exceptions.PreventUpdate
        if not pv_production or not load_consumption:
            return {"color": "blue"}, {"color": "blue"}, ""
        save_entities({"sensor_pv_production": pv_production, "sensor_load_consumption": load_consumption})
        return {"color": "black"}, {"color": "black"}, "saved!"

    @app.callback(
        Output("rebuild-config-status", "children"),
        Input("rebuild-config", "n_clicks"),
        prevent_initial_call=True
    )
    def handle_rebuild_click(n_clicks):
        if n_clicks:
            if recreate_config_file():
                return "Config has been recreated."
            return "Error while recreating config."
        return dash.no_update


def get_sensor_value(entity_id):
    """Fragt einen Sensorwert über die Home Assistant API ab."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return float(response.json()["state"])
    except Exception as e:
        print(f"[ERROR] cant fetch sensor value for {entity_id} :", e)
    return None


