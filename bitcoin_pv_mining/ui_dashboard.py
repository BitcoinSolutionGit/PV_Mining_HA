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
    "netz": "#6666FF",
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

        node_labels = ["PV", "Netzbezug", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"]
        node_colors = [
            COLORS["pv"],
            COLORS["netz"],
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
                source=[0, 0, 1, 1],  # PV und Netz liefern je an Verbraucher
                target=[2, 3, 2, 3],
                value=[3, 2, 2, 1],
                color=[
                    COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
                    COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"],
                    COLORS["heizstab"] if flags.get("heizstab_aktiv") else COLORS["inactive"],
                    COLORS["wallbox"] if flags.get("wallbox_aktiv") else COLORS["inactive"]
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
    html.Button("Neu laden", id="save-button")
])