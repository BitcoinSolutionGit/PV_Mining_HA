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

server = flask.Flask(__name__)

@server.route("/_dash-layout", methods=["GET"])
def test_dash_layout():
    return jsonify({"status": "OK", "hint": "_dash-layout Proxy funktioniert auf Flask-Ebene"})

token = os.getenv("SUPERVISOR_TOKEN")
headers = {"Authorization": f"Bearer {token}"}

try:
    response = requests.get("http://supervisor/addons/self/info", headers=headers)
    print("[SUPERVISOR RESPONSE]", response.status_code)
    addon_data = response.json()
    print(addon_data)

    ingress_url = addon_data["data"].get("ingress_url", "/")
    if not ingress_url.endswith("/"):
        ingress_url += "/"

    print(f"[INFO] Dash läuft mit routes_pathname_prefix = {ingress_url}")

except Exception as e:
    print("[ERROR beim Supervisor-Zugriff]", str(e))
    ingress_url = "/"

app = dash.Dash(
    __name__,
    server=server,
    routes_pathname_prefix=ingress_url,
    requests_pathname_prefix=ingress_url,
    serve_locally=False,
    suppress_callback_exceptions=True
)

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

app.layout = dashboard_layout
register_callbacks(app)

if __name__ == "__main__":
    print("[main.py] Starte Dash auf 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)