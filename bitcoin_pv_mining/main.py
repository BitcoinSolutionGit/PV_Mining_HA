import os
import requests
import dash
import flask
from dash import html, dcc
from dash.dependencies import Input, Output
from flask import send_from_directory
from ui_dashboard import layout as dashboard_layout, register_callbacks
from services.btc_api import update_btc_data_periodically
from ui_pages.sensors import layout as sensors_layout, register_callbacks as reg_sensors
from services.license import verify_license, start_heartbeat_loop, is_premium_enabled, issue_token_and_enable, has_valid_token_cached
from flask import request, redirect
from services.utils import get_addon_version


# beim Start
verify_license()
start_heartbeat_loop(addon_version=get_addon_version())

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

def resolve_icon_source():
    # 1) Container-Pfad
    c1 = "/app/icon.png"
    if os.path.exists(c1):
        return c1
    # 2) Lokal neben main.py
    c2 = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(c2):
        return c2
    return None

ICON_SOURCE_PATH = resolve_icon_source()
ICON_TARGET_PATH = "/config/pv_mining_addon/icon.png"

# Copy icon if it doesn't exist
if ICON_SOURCE_PATH and not os.path.exists(ICON_TARGET_PATH):
    try:
        os.makedirs(os.path.dirname(ICON_TARGET_PATH), exist_ok=True)
        import shutil
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

# --- OAuth Placeholder Routes ---
def _abs_url(path: str) -> str:
    # Baut absolute URL inkl. Ingress-Prefix
    base = request.host_url.rstrip('/')  # z.B. https://ha.local:8123/
    p = prefix if prefix.endswith('/') else prefix + '/'
    if path.startswith('/'):
        path = path[1:]
    return f"{base}{p}{path}"

@app.server.route(f"{prefix}oauth/start")
def oauth_start():
    issue_token_and_enable(sponsor="demo_user", plan="monthly")
    return redirect(prefix)

@app.server.route(f"{prefix}oauth/callback")
def oauth_callback():
    # HEUTE: keine echte Verarbeitung nötig – zurück zur App
    return redirect(prefix)

    # SPÄTER:
    # code = request.args.get("code", "")
    # redirect_uri = _abs_url("oauth/callback")
    # ok = complete_github_oauth(code, redirect_uri)
    # return redirect(prefix)


@app.server.route("/_dash-layout", methods=["GET"])
def dash_ping():
    return {"status": "OK"}

@app.server.route('/config-icon')
def serve_icon():
    return send_from_directory(CONFIG_DIR, 'icon.png')

@dash.callback(
    Output("premium-enabled","data", allow_duplicate=True),
    Input("btn-premium","n_clicks"),
    prevent_initial_call=True
)
def on_click_premium(n):
    if not n:
        raise dash.exceptions.PreventUpdate
    if has_valid_token_cached():
        print("[LICENSE] click: token already valid, skipping issue", flush=True)
        verify_license()
    else:
        issue_token_and_enable(sponsor="demo_user", plan="monthly")
    return {"enabled": is_premium_enabled()}

@dash.callback(
    Output("btn-premium", "className"),
    Output("btn-premium", "children"),
    Input("premium-enabled", "data")
)
def toggle_premium_button(data):
    enabled = bool((data or {}).get("enabled"))
    if enabled:
        # Button ausblenden ODER als „aktiv“ markieren – du kannst hier entscheiden:
        # Variante A: ganz ausblenden:
        # return "custom-tab premium-btn premium-btn-hidden", "Premium Active"
        # Variante B: sichtbar, aber als aktiv:
        return "custom-tab premium-btn premium-btn-active", "Premium Active"
    return "custom-tab premium-btn", "Activate Premium"


@dash.callback(
    Output("active-tab", "data"),
    Output("btn-dashboard", "className"),
    Output("btn-sensors", "className"),
    Input("btn-dashboard", "n_clicks"),
    Input("btn-sensors", "n_clicks"),
    prevent_initial_call=True
)
def switch_tabs(n1, n2):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    active = "dashboard" if button_id == "btn-dashboard" else "sensors"
    return active, \
        "custom-tab custom-tab-selected" if active == "dashboard" else "custom-tab", \
        "custom-tab custom-tab-selected" if active == "sensors" else "custom-tab"

@dash.callback(
    Output("tabs-content", "children"),
    Input("active-tab", "data")
)
def render_tab(tab):
    if tab == "dashboard":
        return dashboard_layout()
    elif tab == "sensors":
        return sensors_layout()


register_callbacks(app)     # Dashboard
reg_sensors(app)            # Sensors


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
                background-color: #ccc;
                color: black;
                font-weight: bold;
                border: 2px solid #999;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
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
            
            .premium-btn {
                background: linear-gradient(#2ecc71, #27ae60);
                color: white;
                font-weight: bold;
                border: 1px solid #1e874b;
            }
            .premium-btn:hover {
                filter: brightness(1.05);
            }
            .premium-btn-hidden {
                display: none;
            }
            .premium-btn-active {
                background: #e0ffe9;
                color: #1e874b;
                border: 2px solid #1e874b;
                cursor: default;
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
    dcc.Store(id="premium-enabled", data={"enabled": is_premium_enabled()}),
    # dcc.Interval(id="license-poll", interval=30_000, n_intervals=0),  # <- wird erst später genutzt


    html.Div([
        html.Img(src=f"{prefix}config-icon", className="header-icon"),
        html.Button("Dashboard", id="btn-dashboard", n_clicks=0, className="custom-tab custom-tab-selected", **{"data-tab": "dashboard"}),
        html.Button("Sensors", id="btn-sensors", n_clicks=0, className="custom-tab", **{"data-tab": "sensors"}),
        # Spacer + Premium-Button ganz rechts
        html.Div(style={"flex": "1"}),
        html.Button("Activate Premium", id="btn-premium", n_clicks=0, className="custom-tab premium-btn"),
    ], id="tab-buttons", className="header-bar"),

    html.Div(id="tabs-content", style={"marginTop": "10px"})
])



if __name__ == "__main__":
    print("[main.py] Starting Dash on 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)