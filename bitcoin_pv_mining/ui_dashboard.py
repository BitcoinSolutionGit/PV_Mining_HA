import os
import yaml
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go
from ha_sensors import get_sensor_value

CONFIG_PATH = "/config/pv_mining_addon/pv_mining_local_config.yaml"

COLORS = {
    "pv": "#FFD700",
    "heizstab": "#3399FF",
    "wallbox": "#33CC66",
    "hausbatterie": "#FF9900",
    "verbrauch": "#A0A0A0",
    "inactive": "#DDDDDD"
}

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print("[WARN] Konfigurationsdatei fehlt oder ungültig:", e)
        return {}

def register_callbacks(app):
    @app.callback(
        Output("sankey-diagram", "figure"),
        #Input("save-button", "n_clicks")
        Input("pv-update", "n_intervals")
    )
    def update_gauge(_):
        config = load_config()
        sensor_id = config.get("entities", {}).get("sensor_pv")
        value = get_sensor_value(sensor_id) if sensor_id else 0

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=value or 0,
            title={"text": "PV-Erzeugung (kW)"},
            gauge={
                "axis": {"range": [0, 5]},
                "bar": {"color": "green"},
                "steps": [
                    {"range": [0, 2.5], "color": "#e0f7e0"},
                    {"range": [2.5, 5], "color": "#c0e0c0"}
                ]
            }
        ))
        fig.update_layout(
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="white"
        )
        return fig

    def update_sankey(_):
        config = load_config()
        flags = config.get("feature_flags", {})

        node_labels = ["PV", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"]
        node_colors = [
            COLORS["pv"],
            COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
            COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"],
            COLORS["hausbatterie"] if flags.get("hausbatterie_aktiv") else COLORS["inactive"],
            COLORS["verbrauch"]
        ]

        fig = go.Figure(data=[go.Sankey(
            node=dict(
                label=node_labels,
                pad=30,
                thickness=25,
                line=dict(color="black", width=0.5),
                color=node_colors
            ),
            link=dict(
                source=[0, 0, 0, 0],
                target=[1, 2, 3, 4],
                value=[4, 3, 2, 1],
                color=[
                    COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
                    COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"],
                    COLORS["hausbatterie"] if flags.get("hausbatterie_aktiv") else COLORS["inactive"],
                    COLORS["verbrauch"]
                ]
            )
        )])

        fig.update_layout(
            font=dict(size=14, color="black"),
            plot_bgcolor='white',
            paper_bgcolor='white',
            margin=dict(l=20, r=20, t=40, b=20)
        )

        return fig

layout = html.Div([
    html.H1("PV Mining Dashboard"),
    dcc.Graph(id="sankey-diagram", figure=go.Figure()),
    dcc.Graph(id="pv-gauge"),
    dcc.Interval(id="pv-update", interval=10_000, n_intervals=0)
    html.Button("Neu laden", id="save-button")
])