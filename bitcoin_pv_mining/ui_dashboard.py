import os
import yaml
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# Konfigurationspfad ermitteln
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "ui_config.yaml")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

def register_callbacks(app):
    @app.callback(
        Output("sankey-diagram", "figure"),
        Input("save-button", "n_clicks")
    )
    def update_sankey(_):
        try:
            print("Callback triggered – Lade Konfiguration")
            config = load_config()
            flags = config.get("feature_flags", {})
            print("Konfiguration:", flags)
        except Exception as e:
            print("Fehler beim Laden der Konfiguration:", e)
            return go.Figure()

        node_colors = [
            "gold",  # PV
            "blue" if flags.get("heizstab_aktiv") else "lightgray",
            "green" if flags.get("wallbox_aktiv") else "lightgray",
            "orange" if flags.get("hausbatterie_aktiv") else "lightgray",
            "gray"  # Hausverbrauch
        ]

        fig = go.Figure(data=[go.Sankey(
            node=dict(
                label=["PV", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"],
                pad=15,
                thickness=20,
                color=node_colors
            ),
            link=dict(
                source=[0, 0, 0, 0],
                target=[1, 2, 3, 4],
                value=[4, 3, 2, 1]
            )
        )])
        return fig

layout = html.Div([
    html.H1("PV Mining Dashboard"),
    dcc.Graph(id="sankey-diagram", figure=go.Figure()),
    html.Button("Neu laden", id="save-button")
])