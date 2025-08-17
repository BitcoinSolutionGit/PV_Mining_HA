import os
import requests
import dash
import flask

from dash import html, dcc
from dash.dependencies import Input, Output
from flask import send_from_directory, request, redirect

from ui_dashboard import layout as dashboard_layout, register_callbacks
from services.btc_api import update_btc_data_periodically
from services.license import (
    verify_license, start_heartbeat_loop, is_premium_enabled,
    issue_token_and_enable, has_valid_token_cached
)
from services.utils import get_addon_version

from ui_pages.sensors import layout as sensors_layout, register_callbacks as reg_sensors
from ui_pages.miners import layout as miners_layout, register_callbacks as reg_miners
from ui_pages.electricity import layout as electricity_layout, register_callbacks as reg_electricity
from ui_pages.battery import layout as battery_layout, register_callbacks as reg_battery
from ui_pages.wallbox import layout as wallbox_layout, register_callbacks as reg_wallbox
from ui_pages.heater import layout as heater_layout, register_callbacks as reg_heater
from ui_pages.settings import layout as settings_layout, register_callbacks as reg_settings

# Lizenz / Heartbeat
verify_license()
start_heartbeat_loop(addon_version=get_addon_version())

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

def resolve_icon_source():
    p1 = "/app/icon.png"
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(p2):
        return p2
    return None

ICON_SOURCE_PATH = resolve_icon_source()
ICON_TARGET_PATH = os.path.join(CONFIG_DIR, "icon.png")

# Icon kopieren (einmalig)
if ICON_SOURCE_PATH and not os.path.exists(ICON_TARGET_PATH):
    try:
        os.makedirs(os.path.dirname(ICON_TARGET_PATH), exist_ok=True)
        import shutil
        shutil.copy(ICON_SOURCE_PATH, ICON_TARGET_PATH)
        print("[INFO] Icon copied to config directory.")
    except Exception as e:
        print(f"[ERROR] Failed to copy icon: {e}")

# BTC-Updater starten
update_btc_data_periodically(CONFIG_PATH)
server = flask.Flask(__name__)

def get_ingress_prefix():
    token = os.getenv("SUPERVISOR_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.get("http://supervisor/addons/self/info", headers=headers, timeout=3)
        if resp.status_code == 200:
            ingress_url = resp.json()["data"]["ingress_url"]
            print(f"[INFO] Supervisor ingress URL: {ingress_url}")
            return ingress_url
        else:
            print(f"[WARN] Supervisor answer: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Supervisor API error: {e}")
    return "/"

prefix = get_ingress_prefix()
if not prefix.endswith("/"):
    prefix += "/"

app = dash.Dash(
    __name__,
    server=server,
    routes_pathname_prefix="/",
    requests_pathname_prefix=prefix,
    suppress_callback_exceptions=True,
    serve_locally=True,
)

print(f"[INFO] Dash runs with requests_pathname_prefix = {prefix}")

# --- OAuth Placeholder Routes ---
def _abs_url(path: str) -> str:
    base = request.host_url.rstrip('/')
    p = prefix if prefix.endswith('/') else prefix + '/'
    path = path[1:] if path.startswith('/') else path
    return f"{base}{p}{path}"

@app.server.route(f"{prefix}oauth/start")
def oauth_start():
    issue_token_and_enable(sponsor="demo_user", plan="monthly")
    return redirect(prefix)

@app.server.route(f"{prefix}oauth/callback")
def oauth_callback():
    return redirect(prefix)

@app.server.route("/_dash-layout", methods=["GET"])
def dash_ping():
    return {"status": "OK"}

@app.server.route('/config-icon')
def serve_icon():
    return send_from_directory(CONFIG_DIR, 'icon.png')


# --- Premium Button ---
@dash.callback(
    Output("premium-enabled", "data", allow_duplicate=True),
    Input("btn-premium", "n_clicks"),
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
        return "custom-tab premium-btn premium-btn-active", "Premium Active"
    return "custom-tab premium-btn premium-btn-locked", "Activate Premium"


# --- Tabs ---
@dash.callback(
    Output("active-tab", "data"),
    Output("btn-dashboard", "className"),
    Output("btn-sensors", "className"),
    Output("btn-miners", "className"),
    Output("btn-electricity", "className"),
    Output("btn-battery", "className"),
    Output("btn-heater", "className"),
    Output("btn-wallbox", "className"),
    Output("btn-settings", "className"),
    Input("btn-dashboard", "n_clicks"),
    Input("btn-sensors", "n_clicks"),
    Input("btn-miners", "n_clicks"),
    Input("btn-electricity", "n_clicks"),
    Input("btn-battery", "n_clicks"),
    Input("btn-heater", "n_clicks"),
    Input("btn-wallbox", "n_clicks"),
    Input("btn-settings", "n_clicks"),
    Input("premium-enabled", "data"),
    prevent_initial_call=True
)
def switch_tabs(n1, n2, n3, n4, n5, n6, n7, n8, premium_data):
    enabled = bool((premium_data or {}).get("enabled"))
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    btn = ctx.triggered[0]["prop_id"].split(".")[0]

    target = "dashboard"
    if btn == "btn-sensors":
        target = "sensors"
    elif btn == "btn-miners":
        target = "miners"
    elif btn == "btn-electricity":
        target = "electricity"
    elif btn == "btn-battery":
        target = "battery" if enabled else "dashboard"
    elif btn == "btn-heater":
        target = "heater" if enabled else "dashboard"
    elif btn == "btn-wallbox":
        target = "wallbox" if enabled else "dashboard"
    elif btn == "btn-settings":
        target = "settings"

    return (
        target,
        "custom-tab custom-tab-selected" if target == "dashboard" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "sensors" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "miners" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "electricity" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "battery" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "heater" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "wallbox" else "custom-tab",
        "custom-tab custom-tab-selected" if target == "settings" else "custom-tab",
    )

def premium_upsell():
    return html.Div([
        html.H3("Premium Feature"),
        html.P("Dieses Feature ist mit Premium verfügbar."),
        html.Button("Activate Premium", id="btn-premium", n_clicks=0, className="custom-tab premium-btn")
    ], style={"textAlign": "center", "padding": "20px"})

@dash.callback(
    Output("btn-battery", "className", allow_duplicate=True),
    Input("premium-enabled", "data"),
    Input("active-tab", "data"),
    prevent_initial_call=True
)
def style_btn_battery(premium_data, active_tab):
    enabled = bool((premium_data or {}).get("enabled"))
    classes = ["custom-tab"]
    if active_tab == "battery":
        classes.append("custom-tab-selected")
    classes.append("battery-premium-ok" if enabled else "battery-premium-locked")
    return " ".join(classes)

@dash.callback(
    Output("btn-heater", "className", allow_duplicate=True),
    Input("premium-enabled", "data"),
    Input("active-tab", "data"),
    prevent_initial_call=True
)
def style_btn_heater(premium_data, active_tab):
    enabled = bool((premium_data or {}).get("enabled"))
    classes = ["custom-tab"]
    if active_tab == "heater":
        classes.append("custom-tab-selected")
    classes.append("heater-premium-ok" if enabled else "heater-premium-locked")
    return " ".join(classes)

@dash.callback(
    Output("btn-wallbox", "className", allow_duplicate=True),
    Input("premium-enabled", "data"),
    Input("active-tab", "data"),
    prevent_initial_call=True
)
def style_btn_wallbox(premium_data, active_tab):
    enabled = bool((premium_data or {}).get("enabled"))
    classes = ["custom-tab"]
    if active_tab == "wallbox":
        classes.append("custom-tab-selected")
    classes.append("wallbox-premium-ok" if enabled else "wallbox-premium-locked")
    return " ".join(classes)

@dash.callback(
    Output("tabs-content", "children"),
    Input("active-tab", "data"),
    Input("premium-enabled", "data")
)
def render_tab(tab, premium_data):
    enabled = bool((premium_data or {}).get("enabled"))
    if tab == "dashboard":
        return dashboard_layout()
    if tab == "sensors":
        return sensors_layout()
    if tab == "miners":
        return miners_layout() if enabled else premium_upsell()
    if tab == "electricity":
        return electricity_layout()
    if tab == "battery":
        return battery_layout()
    if tab == "heater":
        return heater_layout()
    if tab == "wallbox":
        return wallbox_layout()
    if tab == "settings":
        return settings_layout()
    return dashboard_layout()

# Register callbacks
register_callbacks(app)
reg_sensors(app)
reg_electricity(app)
reg_miners(app)
reg_battery(app)
reg_heater(app)
reg_wallbox(app)
reg_settings(app)

# Index / Layout
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Bitcoin PV-mining dashboard</title>
        {%favicon%}
        {%css%}
        <style>
            body { background-color: white; color: black; font-family: Arial, sans-serif; }
            .custom-tab { background-color: #eee; border: 1px solid #ccc; border-radius: 4px;
                          padding: 6px 12px; font-size: 14px; cursor: pointer; transition: all .2s; }
            .custom-tab:hover { background-color: #ddd; }
            .custom-tab-selected { background-color: #ccc; color: black; font-weight: bold;
                                   border: 2px solid #999; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
            @media (max-width: 600px) { .custom-tab { font-size: 12px; padding: 4px 8px; } }
            .header-bar { display:flex; justify-content:center; align-items:center; gap:12px; flex-wrap:wrap; padding:8px; }
            .header-icon { width:32px; height:32px; }
            .premium-btn { background: linear-gradient(#2ecc71, #27ae60); color:white; font-weight:bold; border:1px solid #1e874b; }
            .premium-btn:hover { filter: brightness(1.05); }
            .premium-btn-active { background:#e0ffe9; color:#1e874b; border:2px solid #1e874b; cursor:default; }
            .premium-btn-locked { background: linear-gradient(#e57373, #e53935); color:white; font-weight:bold; border:1px solid #b71c1c; }
            .custom-tab.battery-premium-ok { border-color:#27ae60!important; }
            .custom-tab.battery-premium-locked { border-color:#e74c3c!important; }
            .custom-tab.heater-premium-ok { border-color:#27ae60!important; }
            .custom-tab.heater-premium-locked { border-color:#e74c3c!important; }
            .custom-tab.wallbox-premium-ok { border-color:#27ae60!important; }
            .custom-tab.wallbox-premium-locked { border-color:#e74c3c!important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>{%config%}{%scripts%}{%renderer%}</footer>
    </body>
</html>
'''

app.layout = html.Div([
    dcc.Store(id="active-tab", data="dashboard"),
    dcc.Store(id="premium-enabled", data={"enabled": is_premium_enabled()}),
    # Globaler Store für die Prioritätenliste (persistiert im Browser)
    dcc.Store(id="prio-order", storage_type="local"),

    html.Div([
        html.Img(src=f"{prefix}config-icon", className="header-icon"),
        html.Button("Dashboard",    id="btn-dashboard",    n_clicks=0, className="custom-tab custom-tab-selected"),
        html.Button("Sensors",      id="btn-sensors",      n_clicks=0, className="custom-tab"),
        html.Button("Miners",       id="btn-miners",       n_clicks=0, className="custom-tab"),
        html.Button("Electricity",  id="btn-electricity",  n_clicks=0, className="custom-tab"),
        html.Button("Battery",      id="btn-battery",      n_clicks=0, className="custom-tab"),
        html.Button("Water Heater", id="btn-heater",       n_clicks=0, className="custom-tab"),
        html.Button("Wall-Box",     id="btn-wallbox",      n_clicks=0, className="custom-tab"),
        html.Button("Settings",     id="btn-settings",     n_clicks=0, className="custom-tab"),
        html.Div(style={"flex": "1"}),
        html.Button("Activate Premium", id="btn-premium", n_clicks=0, className="custom-tab premium-btn"),
    ], id="tab-buttons", className="header-bar"),

    html.Div(id="tabs-content", style={"marginTop": "10px"})
])

if __name__ == "__main__":
    print("[main.py] Starting Dash on 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)
