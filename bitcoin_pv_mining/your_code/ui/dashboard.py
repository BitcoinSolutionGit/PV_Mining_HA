# Sankey-Diagramm Vorbereitung
import json
import dash
from dash import html, dcc, Input, Output
import plotly.graph_objects as go

CONFIG_PATH = "config.json"

app = dash.Dash(__name__, requests_pathname_prefix="/")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

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

app.layout = html.Div([
    html.H1("PV Steuerung Dashboard"),
    dcc.Graph(id="sankey-diagram"),
    html.Button("Neu laden", id="save-button")
])

if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8050)
