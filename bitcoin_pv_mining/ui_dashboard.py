import os
import yaml
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# Konfigurationspfad ermitteln
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "ui_config.yaml")

COLORS = {
    "pv": "#FFD700",
    "heizstab": "#3399FF",
    "wallbox": "#33CC66",
    "hausbatterie": "#FF9900",
    "verbrauch": "#A0A0A0",
    "inactive": "#DDDDDD"
}

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
            COLORS["pv"],
            COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
            COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"],
            COLORS["hausbatterie"] if flags.get("hausbatterie_aktiv") else COLORS["inactive"],
            COLORS["verbrauch"]
        ]

        link_colors = [
            COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
            COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"],
            COLORS["hausbatterie"] if flags.get("hausbatterie_aktiv") else COLORS["inactive"],
            COLORS["verbrauch"]
        ]

        fig = go.Figure(data=[go.Sankey(
            node=dict(
                label=["PV", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"],
                pad=30,
                thickness=25,
                line=dict(color="black", width=0.5),
                color=node_colors
            ),
            link=dict(
                source=[0, 0, 0, 0],
                target=[1, 2, 3, 4],
                value=[4, 3, 2, 1],
                color=link_colors
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
    html.Button("Neu laden", id="save-button")
])