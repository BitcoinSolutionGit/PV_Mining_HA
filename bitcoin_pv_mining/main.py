import os
import requests
import dash
from dash import html
import flask
from flask import jsonify
from ui_dashboard import layout as dashboard_layout, register_callbacks

# Lokale Konfig sicherstellen
CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

if not os.path.exists(CONFIG_PATH):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        default_content = """feature_flags:
  heizstab_aktiv: false
  wallbox_aktiv: false
  hausbatterie_aktiv: false
"""
        with open(CONFIG_PATH, "w") as f:
            f.write(default_content)
        print(f"[INIT] Standardkonfiguration erstellt unter: {CONFIG_PATH}")
    except Exception as e:
        print(f"[FEHLER] Konnte Konfiguration nicht anlegen: {e}")


# # Supervisor-Token holen - das liefert echt viele infos zum debugen. sonst auskommentiert lassen!
# test_token = os.getenv("SUPERVISOR_TOKEN")
# test_headers = {"Authorization": f"Bearer {test_token}"}
#
# try:
#     test_response = requests.get("http://supervisor/addons/self/info", headers=test_headers)
#     print("[SUPERVISOR RESPONSE]", test_response.status_code)
#     print(test_response.json())
# except Exception as e:
#     print("[ERROR beim Supervisor-Zugriff]", str(e))


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
        <style>
            body {
                background-color: white;
                color: black;
                font-family: Arial, sans-serif;
            }
        </style>
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
app.layout = dashboard_layout
register_callbacks(app)
# app.layout = html.Div([
#     html.H2("Testseite"),
#     html.P("Wenn du das hier siehst, funktioniert das Layout grundsätzlich.")
# ])


if __name__ == "__main__":
    print("[main.py] Starte Dash auf 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)