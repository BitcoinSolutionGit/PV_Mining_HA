# import os
# import yaml
# import dash
# from dash import html, dcc
# from dash.dependencies import Input, Output
# import plotly.graph_objects as go
#
# # Ingress-kompatibler Pfad
# requests_prefix = os.getenv("INGRESS_ENTRY", "/")
# if not requests_prefix.endswith("/"):
#     requests_prefix += "/"
#
# app = dash.Dash(
#     __name__,
#     routes_pathname_prefix=requests_prefix,
#     requests_pathname_prefix=requests_prefix,
#     serve_locally=True
# )
#
#
# server = app.server  # wichtig für Home Assistant
#
# # Optional: sichere Dash-Kompatibilität
# app.index_string = '''
# <!DOCTYPE html>
# <html>
#     <head>
#         {%metas%}
#         <title>Bitcoin PV Dashboard</title>
#         {%favicon%}
#         {%css%}
#     </head>
#     <body>
#         {%app_entry%}
#         <footer>
#             {%config%}
#             {%scripts%}
#             {%renderer%}
#         </footer>
#     </body>
# </html>
# '''
# #
# # # Konfigpfad – zeigt auf interne Konfigurationsdatei
# # BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# # CONFIG_PATH = os.path.join(BASE_DIR, "config_ui.yaml")
# #
# # def load_config():
# #     try:
# #         with open(CONFIG_PATH, "r") as f:
# #             return yaml.safe_load(f)
# #     except Exception as e:
# #         print("Fehler beim Laden der Konfiguration:", e)
# #         return {}
# #
# # @app.callback(
# #     Output("sankey-diagram", "figure"),
# #     Input("save-button", "n_clicks")
# # )
# # def update_sankey(_):
# #     try:
# #         print("Callback triggered – Lade Konfiguration")
# #         config = load_config()
# #         flags = config.get("feature_flags", {})
# #         print("Konfiguration:", flags)
# #     except Exception as e:
# #         print("Fehler beim Laden der Konfiguration:", e)
# #         return go.Figure()
# #
# #     node = dict(
# #         label=["PV", "Heizstab", "Wallbox", "Hausbatterie", "Hausverbrauch"],
# #         pad=15,
# #         thickness=20,
# #         color=[
# #             "gold",  # PV
# #             "blue" if flags.get("heizstab_aktiv") else "lightgray",
# #             "green" if flags.get("wallbox_aktiv") else "lightgray",
# #             "orange" if flags.get("hausbatterie_aktiv") else "lightgray",
# #             "gray"  # Hausverbrauch
# #         ]
# #     )
# #
# #     link = dict(
# #         source=[0, 0, 0, 0],
# #         target=[1, 2, 3, 4],
# #         value=[4, 3, 2, 1]
# #     )
# #
# #     return go.Figure(go.Sankey(node=node, link=link))
# #
# # # Layout
# # print("[main.py] Setze Layout")
# # app.layout = html.Div([
# #     html.H1("PV Mining Dashboard"),
# #     dcc.Graph(id="sankey-diagram", figure=go.Figure()),
# #     html.Button("Neu laden", id="save-button")
# # ])
# #
# # # Start der Dash-App (Pflicht für Ingress!)
# # if __name__ == "__main__":
# #     print("[main.py] Starte Dash App auf 0.0.0.0:21000")
# #     app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)












# import os
# import dash
# import requests
# import json
# from dash import html
#
# # Supervisor-Token holen
# token = os.getenv("SUPERVISOR_TOKEN")
# headers = {"Authorization": f"Bearer {token}"}
#
# try:
#     response = requests.get("http://supervisor/addons/self/info", headers=headers)
#     print("[SUPERVISOR RESPONSE]", response.status_code)
#     print(response.json())
# except Exception as e:
#     print("[ERROR beim Supervisor-Zugriff]", str(e))
#
#
#
# raw_prefix = os.getenv("INGRESS_ENTRY")
# if raw_prefix and raw_prefix.strip() != "":
#     requests_prefix = raw_prefix
#     print(f"[INFO] INGRESS_ENTRY erkannt: {requests_prefix}")
# else:
#     requests_prefix = "/"
#     print("[WARN] INGRESS_ENTRY nicht gesetzt – verwende Fallback '/'")
#
# if not requests_prefix.endswith("/"):
#     requests_prefix += "/"
#
#
# # print("\n--- 🔍 ALLE Umgebungsvariablen ---")
# # for key, value in os.environ.items():
# #     print(f"[ENV] {key} = {value}")
# # print("--- ENDE ---\n")
#
#
# app = dash.Dash(
#     __name__,
#     url_base_pathname=requests_prefix,
#     serve_locally=False,
#     suppress_callback_exceptions=True
# )
#
# # @app.server.before_request
# # def set_ingress_prefix():
# #     global app
# #     if not hasattr(app, "requests_pathname_prefix_set"):
# #         prefix = request.path.split("/", 4)
# #         if len(prefix) >= 5:
# #             ingress_prefix = "/" + "/".join(prefix[:5]) + "/"
# #             app.config.requests_pathname_prefix = ingress_prefix
# #             app.config.routes_pathname_prefix = ingress_prefix
# #             print(f"[Dynamisch erkannt] Prefix: {ingress_prefix}")
# #             app.requests_pathname_prefix_set = True
#
#
# # HTML-Template
# app.index_string = '''
# <!DOCTYPE html>
# <html>
#     <head>
#         {%metas%}
#         <title>Bitcoin PV Dashboard</title>
#         {%favicon%}
#         {%css%}
#     </head>
#     <body>
#         {%app_entry%}
#         <footer>
#             {%config%}
#             {%scripts%}
#             {%renderer%}
#         </footer>
#     </body>
# </html>
# '''
#
# # Minimal-Layout für Test
# app.layout = html.Div([
#     html.H1("🎉 Bitcoin PV Add-on funktioniert!"),
#     html.P("Wenn du das siehst, klappt Ingress.")
# ])
#
# server = app.server  # Wichtig: erst NACH dem Layout setzen
#
# if __name__ == "__main__":
#     print("[main.py] Starte Dash auf 0.0.0.0:21000")
#     app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)






import os
import dash
import requests
from dash import html
import flask


# Supervisor-Token holen - das liefert echt viele infos zum debugen. sonst auskommentiert lassen!
test_token = os.getenv("SUPERVISOR_TOKEN")
test_headers = {"Authorization": f"Bearer {test_token}"}

try:
    test_response = requests.get("http://supervisor/addons/self/info", headers=test_headers)
    print("[SUPERVISOR RESPONSE]", test_response.status_code)
    print(test_response.json())
except Exception as e:
    print("[ERROR beim Supervisor-Zugriff]", str(e))


server = flask.Flask(__name__)

# Hole Ingress-Pfad zur Laufzeit dynamisch über Supervisor-API
def get_ingress_prefix():
    token = os.getenv("SUPERVISOR_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get("http://supervisor/addons/self/info", headers=headers)
        if response.status_code == 200:
            ingress_url = response.json()["data"]["ingress_url"]
            print(f"[INFO] Supervisor Ingress URL: {ingress_url}")
            return ingress_url
        else:
            print(f"[WARN] Supervisor Antwort: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Supervisor API Fehler: {str(e)}")
    return "/"  # Fallback

prefix = get_ingress_prefix()
if not prefix.endswith("/"):
    prefix += "/"

app = dash.Dash(
    __name__,
    server=server,
    routes_pathname_prefix="/",
    requests_pathname_prefix=prefix,
    serve_locally=False,
    suppress_callback_exceptions=True
)

print(f"[INFO] Dash läuft mit requests_pathname_prefix = {prefix}")

# Optional: Hilfsroute zum Testen
@server.route("/_dash-layout", methods=["GET"])
def dash_ping():
    return {"status": "OK"}

# HTML-Template
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

# Layout
app.layout = html.Div([
    html.H1("🎉 Bitcoin PV Add-on läuft!"),
    html.P("Ingress ist vollständig funktionsfähig.")
])

if __name__ == "__main__":
    print("[main.py] Starte Dash auf 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)
