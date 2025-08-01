import os
import json
import yaml
import dash
from dash import html, dcc, Input, Output
import plotly.graph_objects as go

# Konfigurationspfad ermitteln
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

# Richtig: BASE_PATH nutzen für dynamischen Ingress
requests_prefix = os.getenv("BASE_PATH", "/")
app = dash.Dash(__name__, requests_pathname_prefix=requests_prefix)
server = app.server  # <- Home Assistant erwartet dieses Objekt!

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

@app.callback(
    Output("sankey-diagram", "figure"),
    Input("save-button", "n_clicks")
)
def update_sankey(_):
    config = load_config()
    flags = config.get("feature_flags", {})

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

# UI-Layout
app.layout = html.Div([
    html.H1("PV Mining Dashboard"),
    dcc.Graph(id="sankey-diagram"),
    html.Button("Neu laden", id="save-button")
])

# Dash-App starten – wichtig: host & port fix
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
