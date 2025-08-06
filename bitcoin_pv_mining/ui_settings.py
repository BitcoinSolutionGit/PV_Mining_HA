import yaml
import os
import requests
from dash import html, dcc, Input, Output, State
import dash

CONFIG_PATH = "/config/pv_mining_addon/pv_mining_local_config.yaml"

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
        print("[FEHLER] Beim Speichern der Entities:", e)

def fetch_sensors_from_homeassistant():
    """Liefert eine Liste aller sensor-Entitäten aus HA"""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        print("[WARN] Kein Supervisor-Token für HA-API verfügbar.")
        return []

    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get("http://homeassistant.local:8123/api/states", headers=headers, timeout=5)
        if res.status_code == 200:
            sensors = [e["entity_id"] for e in res.json() if e["entity_id"].startswith("sensor.")]
            return [{"label": s, "value": s} for s in sensors]
        else:
            print(f"[WARN] HA API Fehler: {res.status_code}")
    except Exception as e:
        print(f"[ERROR] Sensor-Abruf fehlgeschlagen: {e}")
    return []

def generate_settings_layout():
    current = load_entities()
    sensor_options = fetch_sensors_from_homeassistant()

    return html.Div([
        html.H2("Sensor-Auswahl"),

        html.Label("Sensor für PV-Produktion"),
        dcc.Dropdown(
            id="sensor-pv",
            options=sensor_options,
            value=current.get("sensor_pv", ""),
            placeholder="Sensor auswählen...",
            style={"width": "100%", "color": "blue"}
        ),

        html.Label("Sensor für Verbrauch", style={"marginTop": "15px"}),
        dcc.Dropdown(
            id="sensor-verbrauch",
            options=sensor_options,
            value=current.get("sensor_verbrauch", ""),
            placeholder="Sensor auswählen...",
            style={"width": "100%", "color": "blue"}
        ),

        html.Button("Speichern", id="save-entities", style={"marginTop": "20px"}),
        html.Div(id="save-status", style={"marginTop": "10px", "color": "green"})
    ])

def register_settings_callbacks(app):
    @app.callback(
        Output("sensor-pv", "style"),
        Output("sensor-verbrauch", "style"),
        Output("save-status", "children"),
        Input("save-entities", "n_clicks"),
        State("sensor-pv", "value"),
        State("sensor-verbrauch", "value")
    )
    def save_inputs(n_clicks, pv, verbrauch):
        if n_clicks is None:
            raise dash.exceptions.PreventUpdate
        if not pv or not verbrauch:
            return {"color": "blue"}, {"color": "blue"}, ""
        save_entities({"sensor_pv": pv, "sensor_verbrauch": verbrauch})
        return {"color": "black"}, {"color": "black"}, "Gespeichert!"
