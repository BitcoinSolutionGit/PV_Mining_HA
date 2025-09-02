import os
import requests
import dash
import flask
import urllib.parse

from dash import html, dcc
from dash.dependencies import Input, Output, State

from flask import send_from_directory
from flask import request, redirect, send_file, Response
from ui_dashboard import layout as dashboard_layout, register_callbacks

from services.btc_api import update_btc_data_periodically
from services.license import set_token, verify_license, start_heartbeat_loop, is_premium_enabled, issue_token_and_enable, has_valid_token_cached
from services.utils import get_addon_version, load_state, save_state
from services.power_planner import plan_and_allocate_auto
from urllib.parse import urlparse, parse_qs

from ui_pages.sensors import layout as sensors_layout, register_callbacks as reg_sensors
from ui_pages.miners import layout as miners_layout, register_callbacks as reg_miners
from ui_pages.electricity import layout as electricity_layout, register_callbacks as reg_electricity
from ui_pages.battery import layout as battery_layout, register_callbacks as reg_battery
from ui_pages.wallbox import layout as wallbox_layout, register_callbacks as reg_wallbox
from ui_pages.heater import layout as heater_layout, register_callbacks as reg_heater
from ui_pages.settings import layout as settings_layout, register_callbacks as reg_settings
from ui_pages.common import footer_license

# beim Start
verify_license()
start_heartbeat_loop(addon_version=get_addon_version())

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")

# GANZ OBEN zusätzlich:
from ui_pages.settings import (
    _prio_available_items as prio_available_items,
    _load_prio_ids as prio_load_ids,
    _prio_merge_with_stored as prio_merge,
)

def _abs_url(path: str) -> str:
    base = request.host_url.rstrip('/')
    p = prefix if prefix.endswith('/') else prefix + '/'
    if path.startswith('/'):
        path = path[1:]
    return f"{base}{p}{path}"

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
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get("http://supervisor/addons/self/info", headers=headers, timeout=5)
        if r.status_code == 200:
            ingress_url = r.json()["data"]["ingress_url"]  # volle URL
            p = urlparse(ingress_url).path or "/"
            if not p.endswith("/"):
                p += "/"
            print(f"[INFO] Ingress path: {p}")
            return p
        else:
            print(f"[WARN] Supervisor answer: {r.status_code}")
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
    requests_pathname_prefix=prefix,  # dein HA-Ingress-Prefix
    suppress_callback_exceptions=True,
    serve_locally=True,
)

try:
    _initial_prio = prio_merge(prio_load_ids(), prio_available_items())
    print("[prio:init] initial order:", _initial_prio, flush=True)
except Exception as e:
    print("[prio:init] failed to compute initial order:", e, flush=True)
    _initial_prio = []

# Zusätzliche (idempotente) Route, falls Dashs interner Assets-Handler am Proxy scheitert
from flask import send_from_directory

print(f"[INFO] Dash runs with requests_pathname_prefix = {prefix}")

server = app.server  # Dash-Server


def _merge_qs_and_hash(search: str | None, hash_: str | None) -> dict:
    """Liest sowohl ?a=b als auch #a=b und merged die Parameter."""
    from urllib.parse import parse_qs
    params = {}
    if search:
        params.update(parse_qs(search.lstrip("?")))
    if hash_:
        h = hash_.lstrip("#")
        if h:
            # parse_qs akzeptiert a=b&c=d
            params.update(parse_qs(h))
    return params


LICENSE_CANDIDATES = [
    "/config/pv_mining_addon/LICENSE",                         # im HA-Config
    os.path.join(os.path.dirname(__file__), "..", "LICENSE"),  # im Add-on/Repo
]

@server.route("/license")
def _serve_license():
    for p in LICENSE_CANDIDATES:
        if os.path.exists(p):
            return send_file(p, mimetype="text/plain")
    return "LICENSE not found", 404


# --- tiny formatter for engine logs ---
def _fmt(x):
    try:
        return f"{float(x):.3f}"
    except Exception:
        return str(x)

def _oauth_start_impl():
    return_url = _abs_url("oauth/finish")
    install_id = load_state().get("install_id", "unknown-install")
    ext = (
        f"{LICENSE_BASE_URL}/oauth_start.php"
        f"?return_url={urllib.parse.quote(return_url, safe='')}"
        f"&install_id={urllib.parse.quote(install_id, safe='')}"
    )
    print("[OAUTH] /oauth/start ->", ext, " prefix=", prefix, flush=True)

    html = f"""
<!doctype html>
<meta charset="utf-8">
<title>Redirecting…</title>
<body style="font-family: system-ui, sans-serif; padding: 16px;">
  <p>Opening GitHub in a new tab…</p>
  <p>If nothing happens, <a href="{ext}" target="_blank" rel="noopener">click here</a>.</p>
  <script>
    (function () {{
      try {{
        window.open("{ext}", "_blank", "noopener");
        window.location.href = "{prefix}";
      }} catch (e) {{
        window.location.href = "{ext}";
      }}
    }})();
  </script>
</body>
"""
    return Response(html, mimetype="text/html")


# Route ohne Prefix (Ingress sieht oft diesen Pfad)
@server.route("/oauth/start")
def oauth_start_root():
    return _oauth_start_impl()

# Route MIT Prefix (falls Ingress nicht strippt)
@server.route(f"{prefix}oauth/start")
def oauth_start_prefixed():
    return _oauth_start_impl()

# def _oauth_finish_impl():
#     print("[OAUTH] /oauth/finish args=", dict(request.args), flush=True)
#
#     err   = request.args.get("error", "")
#     grant = request.args.get("grant", "")
#
#     if err:
#         # return redirect(f"{prefix}?premium_error={urllib.parse.quote(err)}", code=302)
#         return redirect(f"{prefix}?premium_error={urllib.parse.quote(err)}#premium_error={urllib.parse.quote(err)}", code=302)
#
#     if not grant:
#         return redirect(prefix)
#
#     try:
#         install_id = load_state().get("install_id", "unknown-install")
#         r = requests.post(f"{LICENSE_BASE_URL}/redeem.php",
#                           json={"grant": grant, "install_id": install_id},
#                           timeout=10)
#         js = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
#         if js.get("ok") and js.get("token"):
#             set_token(js["token"])
#             verify_license()
#             # return redirect(f"{prefix}?premium=ok", code=302)
#             return redirect(f"{prefix}?premium=ok#premium=ok", code=302)
#         else:
#             # return redirect(f"{prefix}?premium_error=redeem_failed", code=302)
#             return redirect(f"{prefix}?premium_error=redeem_failed#premium_error=redeem_failed", code=302)
#     except Exception as e:
#         print("[OAUTH] redeem error:", e, flush=True)
#         # return redirect(f"{prefix}?premium_error=redeem_exception", code=302)
#         return redirect(f"{prefix}?premium_error=redeem_exception#premium_error=redeem_exception", code=302)

# --- NEU: kleine HTML-Antwort, die den Opener informiert & schließt ---
def _finish_response_js(status: str, err_code: str = ""):
    # Ziel-URLs inkl. Hash, damit dcc.Location(hash=...) triggert
    ok_url   = f"{prefix}?premium=ok#premium=ok"
    err_hash = f"#premium_error={urllib.parse.quote(err_code)}" if err_code else ""
    err_url  = f"{prefix}?premium_error={urllib.parse.quote(err_code)}{err_hash}"

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Done</title>
<body style="font-family: system-ui, sans-serif; padding:16px;">
  <p>Returning to the add-on… You can close this tab.</p>
  <script>
  (function() {{
    var isOk = { 'true' if status == 'ok' else 'false' };
    var err  = {repr(err_code)};
    var target = isOk ? {repr(ok_url)} : {repr(err_url)};
    try {{
      if (window.opener && !window.opener.closed) {{
        try {{
          // Hash setzen → dcc.Location(hash) im Hauptfenster triggert
          window.opener.location.hash = isOk ? "#premium=ok" : ("#premium_error=" + encodeURIComponent(err || "unknown"));
        }} catch (e) {{}}
      }}
    }} catch (e) {{}}
    // Fallback: in diesem Tab zurücknavigieren
    window.location.replace(target);
    setTimeout(function(){{ try {{ window.close(); }} catch (e) {{}} }}, 150);
  }})();
  </script>
</body>"""
    return Response(html, mimetype="text/html")


def _oauth_finish_impl():
    print("[OAUTH] /oauth/finish args=", dict(request.args), flush=True)

    err   = request.args.get("error", "")
    grant = request.args.get("grant", "")

    # Fehler direkt zurückmelden (Opener-Hash + Fallback-Redirect)
    if err:
        return _finish_response_js(status="err", err_code=err)

    if not grant:
        # Nichts zu tun – zurück zur App
        return redirect(prefix)

    try:
        install_id = load_state().get("install_id", "unknown-install")
        r = requests.post(
            f"{LICENSE_BASE_URL}/redeem.php",
            json={"grant": grant, "install_id": install_id},
            timeout=10
        )
        js = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        if js.get("ok") and js.get("token"):
            set_token(js["token"])
            verify_license()
            # Erfolg: Opener informieren
            return _finish_response_js(status="ok")
        else:
            return _finish_response_js(status="err", err_code="redeem_failed")
    except Exception as e:
        print("[OAUTH] redeem error:", e, flush=True)
        return _finish_response_js(status="err", err_code="redeem_exception")


# ✅ neu: ohne Prefix (falls return_url mal „nackt“ kommt)
@server.route("/oauth/finish")
def oauth_finish_root():
    return _oauth_finish_impl()

# ✅ wie gehabt: mit Prefix
@server.route(f"{prefix}oauth/finish")
def oauth_finish_prefixed():
    return _oauth_finish_impl()

@app.server.route('/config-icon')
def serve_icon():
    return send_from_directory(CONFIG_DIR, 'icon.png')


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
    return "custom-tab premium-btn premium-btn-locked", "Activate Premium"

@dash.callback(
    Output("flash-area", "children"),
    Input("url", "search"),
    Input("url", "hash"),
    Input("flash-poll", "n_intervals"),
    prevent_initial_call=False
)
def show_flash(search, hash_, _n):
    # 1) URL (Query + Hash) auswerten
    qs = _merge_qs_and_hash(search, hash_)
    if qs:
        if "premium_error" in qs:
            code = (qs["premium_error"][0] or "").strip()
            messages = {
                "tier_too_low":        "Sponsorship too low: at least $10/month or $100 one-time.",
                "no_sponsor":          "No active sponsorship for BitcoinSolutionGit found.",
                "oauth_denied":        "GitHub login/authorization required.",
                "github_unauthorized": "GitHub rejected the request. Please sign in again.",
                "github_api":          "GitHub API not reachable. Please try again later.",
                "no_token":            "GitHub did not return a token. Please try again.",
                "redeem_failed":       "Could not redeem the license.",
                "redeem_exception":    "Network/server error while redeeming the license.",
            }
            text = messages.get(code, f"Error: {code}")
            return html.Div(text, style={
                "background":"#ffecec","border":"1px solid #e74c3c","padding":"10px",
                "borderRadius":"8px","fontWeight":"bold"
            })
        if qs.get("premium") == ["ok"]:
            return html.Div("Premium activated ✔️", style={
                "background":"#eaffea","border":"1px solid #27ae60","padding":"10px",
                "borderRadius":"8px","fontWeight":"bold"
            })

    # 2) Serverseitiges Flash lesen & verbrauchen
    try:
        st = load_state()
        flash = st.get("ui_flash")
        if flash:
            kind = (flash.get("kind") or "").lower()
            code = flash.get("code") or ""
            # sofort löschen (one-shot)
            st["ui_flash"] = None
            save_state(st)

            if kind == "success" and code == "premium_ok":
                return html.Div("Premium activated ✔️", style={
                    "background":"#eaffea","border":"1px solid #27ae60","padding":"10px",
                    "borderRadius":"8px","fontWeight":"bold"
                })

            if kind == "error":
                messages = {
                    "tier_too_low":        "Sponsorship too low: at least $10/month or $100 one-time.",
                    "no_sponsor":          "No active sponsorship for BitcoinSolutionGit found.",
                    "oauth_denied":        "GitHub login/authorization required.",
                    "github_unauthorized": "GitHub rejected the request. Please sign in again.",
                    "github_api":          "GitHub API not reachable. Please try again later.",
                    "no_token":            "GitHub did not return a token. Please try again.",
                    "redeem_failed":       "Could not redeem the license.",
                    "redeem_exception":    "Network/server error while redeeming the license.",
                }
                text = messages.get(code, f"Error: {code}")
                return html.Div(text, style={
                    "background":"#ffecec","border":"1px solid #e74c3c","padding":"10px",
                    "borderRadius":"8px","fontWeight":"bold"
                })
    except Exception as e:
        print("[FLASH] read error:", e, flush=True)

    return ""


@dash.callback(
    Output("premium-enabled", "data"),
    Input("url", "search"),
    Input("url", "hash"),
    prevent_initial_call=True
)
def refresh_premium_on_return(search, hash_):
    qs = _merge_qs_and_hash(search, hash_)
    if qs.get("premium") == ["ok"]:
        verify_license()
    return {"enabled": is_premium_enabled()}




@dash.callback(
    Output("active-tab", "data"),
    Output("btn-dashboard", "className"),
    Output("btn-sensors", "className"),
    Output("btn-miners", "className"),
    Output("btn-electricity", "className"),
    Output("btn-battery", "className"),
    Output("btn-heater", "className"),
    Output("btn-wallbox", "className"),
    Output("btn-settings","className"),
    Input("btn-dashboard", "n_clicks"),
    Input("btn-sensors", "n_clicks"),
    Input("btn-miners", "n_clicks"),
    Input("btn-electricity", "n_clicks"),
    Input("btn-battery", "n_clicks"),
    Input("btn-heater", "n_clicks"),
    Input("btn-wallbox", "n_clicks"),
    Input("btn-settings","n_clicks"),
    Input("premium-enabled", "data"),
    prevent_initial_call=True
)
def switch_tabs(n1, n2,n3, n4, n5, n6, n7, n8, premium_data):
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
        target = "battery" if enabled else "dashboard"  # Premium required
    elif btn == "btn-heater":
        target = "heater" if enabled else "dashboard"   # Premium required
    elif btn == "btn-wallbox":
        target = "wallbox" if enabled else "dashboard"  # Premium required
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
        html.P("This feature is available with Premium."),
        html.A(
            html.Button("Activate Premium", id="btn-premium-upsell",
                        n_clicks=0, className="custom-tab premium-btn"),
            href=f"{prefix}oauth/start",
            rel="noopener"
        )
    ], style={"textAlign":"center", "padding":"20px"})



@dash.callback(
    Output("btn-battery", "className", allow_duplicate=True),
    Input("premium-enabled", "data"),
    Input("active-tab", "data"),
    prevent_initial_call="initial_duplicate"
)
def style_miners_button(premium_data, active_tab):
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
    prevent_initial_call="initial_duplicate"
)
def style_miners_button(premium_data, active_tab):
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
    prevent_initial_call="initial_duplicate"
)
def style_miners_button(premium_data, active_tab):
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


register_callbacks(app)     # Dashboard
reg_sensors(app)            # Sensors
reg_electricity(app)        # electricity
reg_miners(app)             # miners
reg_battery(app)            # battery
reg_heater(app)             # heater
reg_wallbox(app)            # wallbox
reg_settings(app)           # settings


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
            .premium-btn-locked {
                background: linear-gradient(#e57373, #e53935);
                color: white;
                font-weight: bold;
                border: 1px solid #b71c1c;
            }
            .premium-btn-locked:hover {
                filter: brightness(1.05);
            }
            /* --- Battery-Button: Rahmenfarbe nach Premium-Status --- */
            .custom-tab.battery-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.battery-premium-locked { border-color: #e74c3c !important; }
            /* Wenn der Tab ausgewählt ist, überschreibt diese Regel die Standardauswahlfarbe */
            .custom-tab.battery-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.battery-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }
            /* --- heater-Button: Rahmenfarbe nach Premium-Status --- */
            .custom-tab.heater-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.heater-premium-locked { border-color: #e74c3c !important; }
            /* Wenn der Tab ausgewählt ist, überschreibt diese Regel die Standardauswahlfarbe */
            .custom-tab.heater-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.heater-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }
            /* --- Wallbox-Button: Rahmenfarbe nach Premium-Status --- */
            .custom-tab.wallbox-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.wallbox-premium-locked { border-color: #e74c3c !important; }
            /* Wenn der Tab ausgewählt ist, überschreibt diese Regel die Standardauswahlfarbe */
            .custom-tab.wallbox-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.wallbox-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }
            
            /* Footer (Desktop = eine Zeile, Mobile = 2 Spalten) */
            .footer-stats {
              display: flex;
              flex-wrap: wrap;
              justify-content: center;
              gap: 40px;
              margin-top: 20px;
              width: 100%;
            }
            .footer-stat {
              font-weight: bold;
              text-align: center;
            }
            @media (max-width: 680px) {
              .footer-stats { gap: 12px; }
              .footer-stat { flex: 0 0 calc(50% - 12px); }
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
    dcc.Store(id="prio-order", storage_type="local"),

    dcc.Interval(id="flash-poll", interval=2000, n_intervals=0),

    dcc.Location(id="url", refresh=False),
    html.Div(id="flash-area", style={"margin":"8px 0"}),

    # NEU: globaler Engine-Timer (unabhängig vom Tab)
    dcc.Interval(id="planner-engine", interval=10_000, n_intervals=0),  # alle 10s
    html.Div(id="planner-heartbeat", style={"display": "none"}),        # Dummy-Output

    html.Div([
        html.Img(src=f"{prefix}config-icon", className="header-icon"),
        html.Button("Dashboard", id="btn-dashboard", n_clicks=0, className="custom-tab custom-tab-selected", **{"data-tab": "dashboard"}),
        html.Button("Sensors", id="btn-sensors", n_clicks=0, className="custom-tab", **{"data-tab": "sensors"}),
        html.Button("Miners", id="btn-miners", n_clicks=0, className="custom-tab", **{"data-tab": "miners"}),
        html.Button("Electricity", id="btn-electricity", n_clicks=0, className="custom-tab", **{"data-tab": "electricity"}),
        html.Button("Battery", id="btn-battery", n_clicks=0, className="custom-tab", **{"data-tab": "battery"}),
        html.Button("Water Heater", id="btn-heater", n_clicks=0, className="custom-tab", **{"data-tab": "heater"}),
        html.Button("Wall-Box", id="btn-wallbox", n_clicks=0, className="custom-tab", **{"data-tab": "wallbox"}),
        html.Button("Settings", id="btn-settings", n_clicks=0, className="custom-tab", **{"data-tab":"settings"}),


        # Spacer + Premium-Button ganz rechts
        html.Div(style={"flex": "1"}),
        html.A(
            html.Button("Activate Premium", id="btn-premium",
                        n_clicks=0, className="custom-tab premium-btn"),
            href=f"{prefix}oauth/start",  # bleibt so
            # kein target="_blank" – damit die HA-Session sicher bleibt
            rel="noopener"
        )
        ,
    ], id="tab-buttons", className="header-bar"),

    html.Div(id="tabs-content", style={"marginTop": "10px"})
])

@dash.callback(
    Output("planner-heartbeat", "children"),
    Input("planner-engine", "n_intervals"),
    State("premium-enabled", "data"),
    prevent_initial_call=False
)
def _global_engine_tick(n, premium_data):
    # nur wenn Premium aktiv ist (bei dir ja), sonst still
    enabled = bool((premium_data or {}).get("enabled"))
    if not enabled:
        return ""

    try:
        # schreibt direkt ins Add-on-Log (stdout)
        plan_and_allocate_auto(apply=True, dry_run=False, logger=lambda m: print(m, flush=True))
        return f"ok:{n}"
    except Exception as e:
        print(f"[engine] error: {e}", flush=True)
        return f"err:{n}"


if __name__ == "__main__":
    print("[main.py] Starting Dash on 0.0.0.0:21000")
    app.run(host="0.0.0.0", port=21000, debug=False, use_reloader=False)