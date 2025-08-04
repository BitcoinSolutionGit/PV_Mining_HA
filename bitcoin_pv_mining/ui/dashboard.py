import os
import yaml
import dash
# import dash_html_components as html
# import dash_core_components as dcc
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# Konfigurationspfad ermitteln
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

# Ingress-kompatibler Pfad
requests_prefix = os.getenv("INGRESS_ENTRY", "/")
app = dash.Dash(__name__, requests_pathname_prefix=requests_prefix)
server = app.server  # Home Assistant benötigt dieses Attribut

# Konfig laden
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

# Callback zur Aktualisierung des Sankey-Diagramms
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

# Layout der App
app.layout = html.Div([
    html.H1("PV Mining Dashboard"),
    dcc.Graph(id="sankey-diagram", figure=go.Figure()),
    html.Button("Neu laden", id="save-button")
])

# app.layout = html.Div([
#     html.H1("Hello World Test"),
#     html.Div("Wenn du das siehst, ist die UI korrekt geladen.")
# ])

print("Layout geladen")
# WICHTIG: NICHT app.run() verwenden – Home Assistant startet selbst!
