import os
import yaml
import dash
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# Ingress-kompatibler Pfad
requests_prefix = os.getenv("INGRESS_ENTRY", "/")
if not requests_prefix.endswith("/"):
    requests_prefix += "/"

app = dash.Dash(
    __name__,
    routes_pathname_prefix=requests_prefix,
    requests_pathname_prefix=requests_prefix,
    assets_url_path=requests_prefix + "assets/",
    serve_locally=True
)


server = app.server  # wichtig für Home Assistant

# Optional: sichere Dash-Kompatibilität
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Bitcoin PV Dashboard</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''
#
# # Konfigpfad – zeigt auf interne Konfigurationsdatei
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# CONFIG_PATH = os.path.join(BASE_DIR, "config_ui.yaml")
#
# def load_config():
#     try:
#         with open(CONFIG_PATH, "r") as f:
#             return yaml.safe_load(f)
#     except Exception as e:
#         print("Fehler beim Laden der Konfiguration:", e)
#         return {}
#
# @app.callback(
#     Output("sankey-diagram", "figure"),
#     Input("save-button", "n_clicks")
# )
# def update_sankey(_):
#     try:
#         print("Callback triggered – Lade Konfiguration")
#         config = load_config()
#         flags = config.get("feature_flags", {})
#         print("Konfiguration:", flags)
#     except Exception as e:
#         print("Fehler beim Laden der Konfiguration:", e)
#         return go.Figure()
#
#     node = dict(
#         label=["PV", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"],
#         pad=15,
#         thickness=20,
#         color=[
#             "gold",  # PV
#             "blue" if flags.get("heizstab_aktiv") else "lightgray",
#             "green" if flags.get("wallbox_aktiv") else "lightgray",
#             "orange" if flags.get("hausbatterie_aktiv") else "lightgray",
#             "gray"  # Hausverbrauch
#         ]
#     )
#
#     link = dict(
#         source=[0, 0, 0, 0],
#         target=[1, 2, 3, 4],
#         value=[4, 3, 2, 1]
#     )
#
#     return go.Figure(go.Sankey(node=node, link=link))
#
# # Layout
# print("[main.py] Setze Layout")
# app.layout = html.Div([
#     html.H1("PV Mining Dashboard"),
#     dcc.Graph(id="sankey-diagram", figure=go.Figure()),
#     html.Button("Neu laden", id="save-button")
# ])
#
# # Start der Dash-App (Pflicht für Ingress!)
# if __name__ == "__main__":
#     print("[main.py] Starte Dash App auf 0.0.0.0:21000")
#     app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)

print("Dash Prefix:", requests_prefix)
print("App läuft mit:", app.config.routes_pathname_prefix)

# Layout zu Testzwecken
app.layout = html.Div([
    html.H1("Test Dashboard"),
    html.P("Diese Seite wird korrekt angezeigt."),
])

if __name__ == "__main__":
    print("[main] Starte Dash auf 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)