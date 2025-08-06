import os
import requests
import dash
from dash import html, dcc
import flask
from dash.dependencies import Input, Output
from flask import jsonify, request
from ui_dashboard import layout as dashboard_layout, register_callbacks
from ui_settings import generate_settings_layout, register_settings_callbacks, recreate_config_file

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
# force rebuild button triggers this manually later
FORCE_CREATE_CONFIG = os.getenv("FORCE_CREATE_CONFIG", "false").lower() == "true"

if FORCE_CREATE_CONFIG or not os.path.exists(CONFIG_PATH):
    recreate_config_file()

server = flask.Flask(__name__)

def get_ingress_prefix():
    token = os.getenv("SUPERVISOR_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get("http://supervisor/addons/self/info", headers=headers)
        if response.status_code == 200:
            ingress_url = response.json()["data"]["ingress_url"]
            print(f"[INFO] Supervisor ingress URL: {ingress_url}")
            return ingress_url
        else:
            print(f"[WARN] Supervisor answer: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Supervisor API error: {str(e)}")
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

print(f"[INFO] Dash runs with requests_pathname_prefix = {prefix}")

@app.server.route("/_dash-layout", methods=["GET"])
def dash_ping():
    return {"status": "OK"}

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

app.layout = html.Div([
    dcc.Tabs(id="tabs", value="dashboard", children=[
        dcc.Tab(label="dashboard", value="dashboard"),
        dcc.Tab(label="settings", value="settings"),
    ]),
    html.Div(id="tabs-content")
])

@dash.callback(
    Output("tabs-content", "children"),
    Input("tabs", "value")
)
def render_tab(tab):
    if tab == "dashboard":
        return dashboard_layout
    elif tab == "settings":
        return generate_settings_layout()

register_callbacks(app)
register_settings_callbacks(app)

if __name__ == "__main__":
    print("[main.py] starting dash at 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)