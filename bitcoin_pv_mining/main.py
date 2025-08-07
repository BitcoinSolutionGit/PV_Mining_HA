import os
import shutil
import requests
import dash
from dash import html, dcc
import flask
from dash.dependencies import Input, Output
from flask import jsonify, request
from flask import send_from_directory
from ui_dashboard import layout as dashboard_layout, register_callbacks
from ui_settings import generate_settings_layout, register_settings_callbacks, recreate_config_file
from btc_api import update_btc_data_periodically

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
ICON_SOURCE_PATH = "/app/icon.png"  # im GitHub-Repo
ICON_TARGET_PATH = "/config/pv_mining_addon/icon.png"

# force rebuild button triggers this manually later
FORCE_CREATE_CONFIG = os.getenv("FORCE_CREATE_CONFIG", "false").lower() == "true"

if FORCE_CREATE_CONFIG or not os.path.exists(CONFIG_PATH):
    recreate_config_file()

# Copy icon if it doesn't exist
if not os.path.exists(ICON_TARGET_PATH):
    try:
        shutil.copy(ICON_SOURCE_PATH, ICON_TARGET_PATH)
        print("[INFO] Icon copied to config directory.")
    except Exception as e:
        print(f"[ERROR] Failed to copy icon: {e}")

# Start BTC API updater
update_btc_data_periodically(CONFIG_PATH)
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
@app.server.route('/config-icon')
def serve_icon():
    return send_from_directory(CONFIG_DIR, 'icon.png')

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Bitcoin PV-mining dashboard</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                background-color: white;
                color: black;
                font-family: Arial, sans-serif;
            }
            .custom-tab {
                background-color: #eee;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 14px;
                cursor: pointer;
                transition: all 0.2s ease-in-out;
            }
            .custom-tab:hover {
                background-color: #ddd;
            }
            .custom-tab-selected {
                background-color: #007BFF;
                color: white;
                font-weight: bold;
                border: 2px solid #004080;
                box-shadow: 0 3px 8px rgba(0, 0, 0, 0.3);
            }
            @media (max-width: 600px) {
                .custom-tab {
                    font-size: 12px;
                    padding: 4px 8px;
                }
            }
            .header-bar {
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 12px;
                flex-wrap: wrap;
                padding: 8px;
            }
            .header-icon {
                width: 32px;
                height: 32px;
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
    dcc.Store(id="active-tab", data="dashboard"),

    html.Div([
        html.Img(src="/config-icon", className="header-icon"),
        html.Button("Dashboard", id="btn-dashboard", n_clicks=0, className="custom-tab", **{"data-tab": "dashboard"}),
        html.Button("Settings", id="btn-settings", n_clicks=0, className="custom-tab", **{"data-tab": "settings"}),
    ], id="tab-buttons", className="header-bar"),

    html.Div(id="tabs-content", style={"marginTop": "10px"})
])

@dash.callback(
    Output("active-tab", "data"),
    Output("btn-dashboard", "className"),
    Output("btn-settings", "className"),
    Input("btn-dashboard", "n_clicks"),
    Input("btn-settings", "n_clicks"),
    prevent_initial_call=True
)
def switch_tabs(n1, n2):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    active = "dashboard" if button_id == "btn-dashboard" else "settings"
    return active, \
        "custom-tab custom-tab-selected" if active == "dashboard" else "custom-tab", \
        "custom-tab custom-tab-selected" if active == "settings" else "custom-tab"

@dash.callback(
    Output("tabs-content", "children"),
    Input("active-tab", "data")
)
def render_tab(tab):
    if tab == "dashboard":
        return dashboard_layout
    elif tab == "settings":
        return generate_settings_layout()

register_callbacks(app)
register_settings_callbacks(app)

if __name__ == "__main__":
    print("[main.py] Starting Dash on 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)