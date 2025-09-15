import os
import requests
import dash
import flask
import urllib.parse
import time
import json

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State


from flask import request, redirect, send_file, Response, jsonify
from ui_dashboard import layout as dashboard_layout, register_callbacks

from services.btc_api import update_btc_data_periodically
from services.license import set_token, verify_license, start_heartbeat_loop, is_premium_enabled, issue_token_and_enable, has_valid_token_cached
from services.utils import get_addon_version, load_state, save_state, iso_now, load_yaml
from services.power_planner import plan_and_allocate_auto
from services.settings_store import get_var as settings_get
from urllib.parse import urlparse, parse_qs

from ui_pages.sensors import layout as sensors_layout, register_callbacks as reg_sensors
from ui_pages.miners import layout as miners_layout, register_callbacks as reg_miners
from ui_pages.electricity import layout as electricity_layout, register_callbacks as reg_electricity
from ui_pages.battery import layout as battery_layout, register_callbacks as reg_battery
from ui_pages.wallbox import layout as wallbox_layout, register_callbacks as reg_wallbox
from ui_pages.heater import layout as heater_layout, register_callbacks as reg_heater
from ui_pages.settings import layout as settings_layout, register_callbacks as reg_settings
from ui_pages.dev import layout as dev_layout, register_callbacks as reg_dev
from ui_pages.common import footer_license, page_wrap, ui_background_color

# beim Start
verify_license()
start_heartbeat_loop(addon_version=get_addon_version())

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")
ENABLE_MOBILE_POLLING = os.getenv("ENABLE_MOBILE_POLLING", "0") == "1"

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

IS_INGRESS = prefix.startswith("/api/hassio_ingress/")
print(f"[INFO] IS_INGRESS={IS_INGRESS} prefix={prefix}")

@server.route("/oauth/config.js")
@server.route(f"{prefix}oauth/config.js")
def oauth_config_js():
    val = "true" if ENABLE_MOBILE_POLLING else "false"
    return Response(f"window.__MOBILE_POLLING__={val};", mimetype="application/javascript")

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


def _show_dev_tab() -> bool:
    try:
        cfg = load_yaml(CONFIG_PATH, {}) or {}
        ff  = cfg.get("feature_flags") or {}
        return bool(ff.get("show_dev_tab", False))
    except Exception:
        return False

def _show_battery_tab() -> bool:
    try:
        from services.utils import load_yaml
        cfg = load_yaml(CONFIG_PATH, {}) or {}
        ff  = cfg.get("feature_flags") or {}
        return bool(ff.get("show_battery_tab", False))
    except Exception:
        return False

def _show_wallbox_tab() -> bool:
    try:
        from services.utils import load_yaml
        cfg = load_yaml(CONFIG_PATH, {}) or {}
        ff  = cfg.get("feature_flags") or {}
        return bool(ff.get("show_wallbox_tab", False))
    except Exception:
        return False

SHOW_DEV_TAB = _show_dev_tab()
SHOW_BATTERY_TAB = _show_battery_tab()
SHOW_WALLBOX_TAB = _show_wallbox_tab()


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

# HIER
@server.route("/debug/test_pending")
@server.route(f"{prefix}debug/test_pending")
def debug_test_pending():
    try:
        install_id = load_state().get("install_id", "unknown-install")
        url = f"{LICENSE_BASE_URL}/var/pending/get.php?install_id={urllib.parse.quote(install_id, safe='')}"
        r = requests.get(url, timeout=8)  # timeout etwas höher
        txt = f"URL: {url}\nHTTP {r.status_code}\n\n{r.text[:2000]}"
        print(f"[MOBILE-OAUTH] pending poll: {url}", flush=True)
        return Response(txt, mimetype="text/plain", status=(200 if r.ok else 502))

    except Exception as e:
        return Response(f"URL: {url}\nEXC: {repr(e)}", mimetype="text/plain", status=502)

# HIER
@server.route("/debug/clear_flash")
@server.route(f"{prefix}debug/clear_flash")
def debug_clear_flash():
    st = load_state()
    st.pop("ui_flash", None)
    save_state(st)
    return "OK"

# HIER
@server.route("/debug/install_id")
@server.route(f"{prefix}debug/install_id")
def debug_install_id():
    return Response(load_state().get("install_id","<none>"), mimetype="text/plain")



def _oauth_start_impl():
    return_url = _abs_url("")  # Basispfad, nicht /oauth/finish
    install_id = load_state().get("install_id", "unknown-install")
    ext = (
        f"{LICENSE_BASE_URL}/oauth_start.php"
        f"?return_url={urllib.parse.quote(return_url, safe='')}"
        f"&install_id={urllib.parse.quote(install_id, safe='')}"
    )
    print("[OAUTH] /oauth/start ->", ext, " prefix=", prefix, flush=True)
    return redirect(ext, code=302)
    # if request.args.get("direct") == "1":
    #     return redirect(ext, code=302)
    # # optionaler Fallback-Screen (kannst du auch weglassen)
    # return Response(f'<!doctype html><a href="{ext}" target="_blank">Open GitHub</a>', mimetype="text/html")



from flask import Response
import json

def _finish_notify(status: str, code: str | None = None) -> Response:
    # Payload für postMessage
    payload = {"type": "pvmining:oauth", "status": status}
    if code:
        payload["code"] = code
    js_payload = json.dumps(payload)

    # WICHTIG: Alle JS-Klammern verdoppeln ({{ }}) außer dem {js_payload} Platzhalter.
    html = (
        "<!doctype html>"
        "<meta charset='utf-8'>"
        "<title>Completing…</title>"
        "<body style='font-family: system-ui, sans-serif; padding:16px'>"
        "<p>Finishing sign-in…</p>"
        "<script>"
        "(function () {{"
        "  var data = {js_payload};"
        "  try {{"
        "    if (window.opener && !window.opener.closed) {{"
        "      try {{ window.opener.postMessage(data, '*'); }} catch (_) {{}}"
        "      try {{"
        "        if (data.status === 'ok') {{"
        "          // Für deine Dash-Callback-Logik: zeigt Success-Toast"
        "          window.opener.location.hash = 'premium=ok';"
        "        }} else {{"
        "          window.opener.location.hash = 'premium_error=' + encodeURIComponent(data.code || 'unknown');"
        "        }}"
        "      }} catch (_) {{}}"
        "      window.close();"
        "      return;"
        "    }}"
        "  }} catch (_) {{}}"
        "  // Kein Redirect zur Ingress-URL hier (vermeidet 401 im Popup)"
        "  document.body.innerHTML = '<p>Login finished. Please return to the app tab.</p>';"
        "}})();"
        "</script>"
        "</body>"
    ).format(js_payload=js_payload)

    return Response(html, mimetype="text/html")



# Route ohne Prefix (Ingress sieht oft diesen Pfad)
@server.route("/oauth/start")
def oauth_start_root():
    return _oauth_start_impl()

# Route MIT Prefix (falls Ingress nicht strippt)
@server.route(f"{prefix}oauth/start")
def oauth_start_prefixed():
    return _oauth_start_impl()

# === NEW: build external OAuth URL without touching HA in the new tab ===
@server.route("/oauth/link")
def oauth_link_root():
    return _oauth_link_impl()

@server.route(f"{prefix}oauth/link")
def oauth_link_prefixed():
    return _oauth_link_impl()



def _oauth_link_impl():
    # return_url = Basispfad deines Add-ons (HA-Ingress), NICHT /oauth/finish
    base = request.host_url.rstrip("/")
    ret  = f"{base}{prefix}"  # z.B. http://ha:8123/api/hassio_ingress/<token>/
    install_id = load_state().get("install_id", "unknown-install")
    ext = (
        f"{LICENSE_BASE_URL}/oauth_start.php"
        f"?return_url={urllib.parse.quote(ret, safe='')}"
        f"&install_id={urllib.parse.quote(install_id, safe='')}"
    )
    return flask.jsonify({"url": ext})


@server.route("/oauth/pending")
def oauth_pending_proxy_root():
    return _oauth_pending_proxy_impl()

@server.route(f"{prefix}oauth/pending")
def oauth_pending_proxy_prefixed():
    return _oauth_pending_proxy_impl()

def _oauth_pending_proxy_impl():
    try:
        install_id = load_state().get("install_id", "unknown-install")
        url = f"{LICENSE_BASE_URL}/var/pending/get.php?install_id={urllib.parse.quote(install_id, safe='')}"
        headers = {
            "User-Agent": "pv-mining-addon/1.0 (+https://bitcoinsolution.at)",
            "Accept": "application/json",
        }
        r = requests.get(url, headers=headers, timeout=8)

        # Content-Type „aufräumen“ (einige Hoster schicken text/plain oder gar nichts)
        ct = r.headers.get("content-type", "")
        if not ct or not ct.startswith("application/json"):
            try:
                txt = r.text.strip()
                if txt.startswith("{") or txt.startswith("["):
                    ct = "application/json"
                else:
                    # Lass notfalls den vom Hoster gelieferten Typ stehen (HTML/403 etc.)
                    ct = ct or "text/html"
            except Exception:
                ct = "application/json"

        print(f"[MOBILE-OAUTH] pending poll: {url} -> {r.status_code} ct={ct}", flush=True)
        resp = Response(r.content, status=r.status_code, mimetype=ct)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    except Exception as e:
        # Nur bei echten Verbindungsfehlern liefern wir einen JSON-Fehler zurück.
        # Dein Frontend ignoriert 'pending_proxy_exception' und pollt weiter.
        print(f"[MOBILE-OAUTH] pending proxy error: {repr(e)}", flush=True)
        return jsonify({"status": "error", "code": "pending_proxy_exception"}), 200



def _flash(level: str, code: str) -> None:
    try:
        st = load_state()
        st["ui_flash"] = {"level": level, "code": code, "ts": iso_now()}
        save_state(st)
    except Exception as e:
        print("[FLASH] write error:", e, flush=True)


def _oauth_finish_impl():
    print("[OAUTH] /oauth/finish args=", dict(request.args), flush=True)

    err   = request.args.get("error", "")
    grant = request.args.get("grant", "")

    if err:
        _flash("error", err)                  # <— NEU
        return _finish_notify("error", err)

    if not grant:
        _flash("error", "missing_grant")      # <— NEU
        return _finish_notify("error", "missing_grant")

    try:
        install_id = load_state().get("install_id", "unknown-install")
        r = requests.post(f"{LICENSE_BASE_URL}/redeem.php",
                          json={"grant": grant, "install_id": install_id},
                          timeout=10)
        js = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        if js.get("ok") and js.get("token"):
            set_token(js["token"])
            verify_license()
            _flash("ok", "premium_ok")        # <— NEU
            return _finish_notify("ok", None)
        else:
            _flash("error", "redeem_failed")  # <— NEU
            return _finish_notify("error", "redeem_failed")
    except Exception as e:
        print("[OAUTH] redeem error:", e, flush=True)
        _flash("error", "redeem_exception")   # <— NEU
        return _finish_notify("error", "redeem_exception")


# ✅ neu: ohne Prefix (falls return_url mal „nackt“ kommt)
@server.route("/oauth/finish")
def oauth_finish_root():
    return _oauth_finish_impl()

# ✅ wie gehabt: mit Prefix
@server.route(f"{prefix}oauth/finish")
def oauth_finish_prefixed():
    return _oauth_finish_impl()


@app.callback(
    Output("flash-area", "children"),
    Output("premium-enabled", "data"),
    Output("flash-visible-until", "data"),
    Input("url", "hash"),
    Input("flash-poll", "n_intervals"),
    State("premium-enabled", "data"),
    State("flash-visible-until", "data"),
    prevent_initial_call=False
)
def flash_and_premium(hash_, _n, premium_state, visible_until):
    """
    Zeigt Toasts, wenn der Hash (#premium=ok | #premium_error=CODE) gesetzt wurde
    oder serverseitiges ui_flash vorhanden ist.
    Auto-Hide: nach 10 Sekunden wird der Toast automatisch ausgeblendet.
    """
    messages = {
        "tier_too_low":         "Sponsorship too low: at least $10/month or $100 one-time.",
        "no_sponsor":           "No active sponsorship for BitcoinSolutionGit found.",
        "oauth_denied":         "GitHub login/authorization required.",
        "github_unauthorized":  "GitHub rejected the request. Please sign in again.",
        "github_api":           "GitHub API not reachable. Please try again later.",
        "no_token":             "GitHub did not return a token. Please try again.",
        "redeem_failed":        "Could not redeem the license.",
        "redeem_exception":     "Network/server error while redeeming the license.",
        "missing_grant":        "Login did not complete correctly. Please try again.",
        "premium_ok":           "Premium activated.",
    }
    style_ok  = {"background":"#eaffea","border":"1px solid #27ae60","padding":"10px","borderRadius":"8px","fontWeight":"bold"}
    style_err = {"background":"#ffecec","border":"1px solid #e74c3c","padding":"10px","borderRadius":"8px","fontWeight":"bold"}

    now = time.time()
    toast = None
    new_visible_until = dash.no_update

    # 1) Hash auswerten (kommt via postMessage/storage aus /oauth/finish)
    if hash_:
        h = (hash_ or "").lstrip("#")
        if h == "premium=ok" or h.startswith("premium=ok"):
            toast = html.Div(messages["premium_ok"], style=style_ok)
        elif h.startswith("premium_error="):
            code = h.split("=", 1)[1]
            text = messages.get(code, f"Error: {code}")
            toast = html.Div(text, style=style_err)

    # 2) Optionaler Fallback: serverseitiges ui_flash (one-shot)
    if toast is None:
        try:
            st = load_state()
            flash = st.get("ui_flash")
            if flash:
                code  = (flash.get("code") or "").strip()
                level = flash.get("level") or "error"
                # einmalig konsumieren
                st.pop("ui_flash", None)
                save_state(st)
                if level == "ok":
                    toast = html.Div(messages.get(code, "OK"), style=style_ok)
                else:
                    toast = html.Div(messages.get(code, f"Error: {code}"), style=style_err)
        except Exception as e:
            print("[FLASH] read error:", e, flush=True)

    # --- Auto-Hide-Logik ---
    if toast is not None:
        # Nur starten, wenn NICHT schon ein aktiver Toast läuft (verhindert Reset bei jedem Poll)
        if visible_until and now < float(visible_until):
            toast = dash.no_update
            new_visible_until = visible_until
        else:
            new_visible_until = now + 10.0  # 10 Sekunden sichtbar
    else:
        # Kein neuer Toast – ggf. vorhandenen nach Ablauf entfernen
        if visible_until and now >= float(visible_until):
            toast = ""  # clear
            new_visible_until = 0
        else:
            toast = dash.no_update
            new_visible_until = dash.no_update

    # 3) premium-enabled nur aktualisieren, wenn sich der Wert tatsächlich ändert
    current_enabled = bool((premium_state or {}).get("enabled"))
    now_enabled = is_premium_enabled()
    premium_out = {"enabled": now_enabled} if (now_enabled != current_enabled) else dash.no_update

    return toast, premium_out, new_visible_until



@app.server.route('/config-icon')
def serve_icon():
    return send_from_directory(CONFIG_DIR, 'icon.png')


@app.callback(
    Output("btn-premium", "className"),
    Output("btn-premium", "children"),
    Input("premium-enabled", "data")
)
def toggle_premium_button(data):
    base = "custom-tab premium-btn premium-right"  # <-- premium-right bleibt IMMER dran
    if bool((data or {}).get("enabled")):
        return f"{base} premium-btn-active", "Premium Active"
    return f"{base} premium-btn-locked", "Activate Premium"



@app.callback(
    Output("active-tab", "data"),
    Output("btn-dashboard", "className"),
    Output("btn-sensors", "className"),
    Output("btn-miners", "className"),
    Output("btn-electricity", "className"),
    Output("btn-battery", "className"),
    Output("btn-heater", "className"),
    Output("btn-wallbox", "className"),
    Output("btn-settings","className"),
    Output("btn-dev","className"),
    Input("btn-dashboard", "n_clicks"),
    Input("btn-sensors", "n_clicks"),
    Input("btn-miners", "n_clicks"),
    Input("btn-electricity", "n_clicks"),
    Input("btn-battery", "n_clicks"),
    Input("btn-heater", "n_clicks"),
    Input("btn-wallbox", "n_clicks"),
    Input("btn-settings","n_clicks"),
    Input("btn-dev","n_clicks"),
    State("premium-enabled", "data"),
    prevent_initial_call=True
)
def switch_tabs(n1, n2,n3, n4, n5, n6, n7, n8, n9, premium_data):
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
        target = "battery" if (SHOW_BATTERY_TAB and enabled) else "dashboard"  # Premium required
    elif btn == "btn-heater":
        target = "heater" if enabled else "dashboard"   # Premium required
    elif btn == "btn-wallbox":
        target = "wallbox" if (SHOW_WALLBOX_TAB and enabled) else "dashboard"  # Premium required
    elif btn == "btn-settings":
        target = "settings"
    elif btn == "btn-dev":
        target = "dev"

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
        "custom-tab custom-tab-selected" if target == "dev" else "custom-tab",
    )

def premium_upsell():
    return html.Div([
        html.H3("Premium Feature"),
        html.P("This feature is available with Premium."),
        html.Button("Activate Premium", id="btn-premium-upsell",
                    n_clicks=0, className="custom-tab premium-btn"),
    ], style={"textAlign":"center", "padding":"20px"})


@app.callback(
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

@app.callback(
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

@app.callback(
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

def _show_dev_tab() -> bool:
    try:
        from services.utils import load_yaml
        cfg = load_yaml(CONFIG_PATH, {}) or {}
        ff  = cfg.get("feature_flags") or {}
        return bool(ff.get("show_dev_tab", False))
    except Exception:
        return False

@app.callback(
    Output("tabs-content", "className"),
    Input("active-tab", "data"),
    prevent_initial_call=False
)
def _pad_content(active_tab):
    base = "content-area"
    # Auf dem Dashboard kein Extra-Pad, sonst schon
    return base if active_tab == "dashboard" else f"{base} extra-pad"


@server.route("/debug/clear_token")
@server.route(f"{prefix}debug/clear_token")
def debug_clear_token():
    try:
        from services.license import set_token, verify_license
        set_token("")          # Token entfernen
        verify_license()       # Status neu bewerten
        return "OK (token cleared)", 200
    except Exception as e:
        return f"ERR: {e}", 500

@app.callback(
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
        # ⬇️ früher: return miners_layout() if enabled else premium_upsell()
        return miners_layout()  # Miners-Tab ist immer sichtbar (Miner 2+ werden innen gegated)
    if tab == "electricity":
        return electricity_layout()
    if tab == "battery":
        return battery_layout() if SHOW_BATTERY_TAB else dashboard_layout()
    if tab == "heater":
        return heater_layout()
    if tab == "wallbox":
        return wallbox_layout() if SHOW_WALLBOX_TAB else dashboard_layout()
    if tab == "settings":
        return settings_layout()
    if tab == "dev":
        return dev_layout() if _show_dev_tab() else dashboard_layout()
    return dashboard_layout()


register_callbacks(app)     # Dashboard
reg_sensors(app)            # Sensors
reg_electricity(app)        # electricity
reg_miners(app)             # miners
reg_battery(app)            # battery
reg_heater(app)             # heater
reg_wallbox(app)            # wallbox
reg_settings(app)           # settings
if _show_dev_tab():
    try:
        reg_dev(app)
    except Exception as e:
        print(f"[dev] register error: {e}", flush=True)


app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Bitcoin PV-mining dashboard</title>
        {%favicon%}
        {%css%}
        <style>
            html, body {
                margin: 0 !important;
                padding: 0 !important;
                /* background: var(--bg-color, #ffffff) !important; */
                background: transparent !important; 
                height: 100%;
                color: black;
                font-family: Arial, sans-serif;
            }

            /* Basis-Look der Tabs */
            .custom-tab {
                background-color: #eee;
                border: 1px solid #ccc;
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.2s ease-in-out;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                height: 36px;      /* einheitliche Höhe */
                padding: 0 14px;   /* horizontales Padding */
                font-size: 14px;
            }
            .custom-tab:hover { background-color: #ddd; }
            .custom-tab-selected {
                background-color: #ccc;
                color: black;
                font-weight: bold;
                border: 2px solid #999;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            }

            /* Premium-Button-Styles */
            .premium-btn {
                background: linear-gradient(#2ecc71, #27ae60);
                color: white;
                font-weight: bold;
                border: 1px solid #1e874b;
                height: 36px;      /* gleiche Höhe wie Tabs */
                padding: 0 14px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }
            .premium-btn:hover { filter: brightness(1.05); }
            .premium-btn-hidden { display: none; }
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
            .premium-btn-locked:hover { filter: brightness(1.05); }

            /* Header-Container */
            .header-bar { margin-top: 0 !important; border-top: none !important; position: relative; }

            :root { --header-side-pad: 140px; }
            
            
            
            /* Desktop: Icon absolut, Tabs zentriert, kaum Abstand nach unten */
            @media (min-width: 900px) {
              .header-bar{
                position: relative;             /* Anker für das Icon */
                display: flex;
                justify-content: center;        /* Tabs zentriert */
                align-items: center;
                gap: 12px;
                padding: 6px var(--header-side-pad) 2px var(--header-side-pad);   /* links Platz fürs große Icon */
                margin-bottom: 0;               /* KEIN zusätzlicher Leerraum */
              }
              .header-icon{
                position: absolute;             /* nimmt keine Höhe ein */
                left: 10px;
                top: 6px;
                width: 96px;
                height: 96px;
                cursor: pointer; 
              }
              
              .header-bar .tab-group{
               display: flex;
               flex-wrap: wrap;
               column-gap: 15px;   /* horizontaler Abstand */
               row-gap: 15px;  
                flex: 0 0 auto;            /* NICHT wachsen/strecken */
                margin: 0 auto;            /* Block mittig im Header */
                min-width: 0;              /* falls was min-content bremst */
                
                /* optional: damit sie nicht mit Icon/Premium kollidiert, je nach Größen: */
                /* max-width: calc(100% - 260px); */
              }
              
              .custom-tab{ flex:0 0 auto; } /* Tabs behalten natürliche Breite */
              
              /* Premium-Button ganz rechts im Flex-Header */
                .header-bar { position: relative; }
                .header-bar .premium-right {
                    position: absolute;
                    right: 12px;
                    top: 6px;
                    margin-left: 0 !important;   /* schiebt ihn an den rechten Rand */
                }
                            
              .page-title{
                margin: 2px 0 0;                /* direkt unter die Tabs */
                line-height: 1.2;
                font-size: clamp(26px, 2.4vw, 36px);
                text-align: center;
              }
              
              /* Nur Desktop: Nicht-Dashboard etwas weiter nach unten schieben,
               damit das große Icon nichts überlappt */
            @media (min-width: 900px) {
              .content-area.extra-pad { padding-top: 64px; } /* bei Bedarf 56–80px feinjustieren */
            }
            }



            /* Mobile/Tablet: Icon wieder normal, Tabs wrappen; kleiner Abstand unten ok */
            @media (max-width: 899px) {
              .header-bar{
                position: relative;
                display: flex;
                flex-wrap: wrap; 
                justify-content: center;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;              /* kein extra linker Platz nötig */
                margin-bottom: 4px;
              }
              
              .header-icon{
                position: static;               /* normaler Flow */
                width: 32px;
                height: 32px;
                # margin-right:8px;
                cursor: pointer; 
                order: 0; 
                flex:0 0 auto; 
              }
              
              /* Tab-Container selbst ist auch Flex (damit Buttons schön umbrechen) */
              .tab-group{
                display: contents; 
                # display: flex;
                # flex-wrap: wrap;
                # gap: 8px;
                # order: 1;                  /* dann die Tabs */
                # flex:1 1 0;         /* darf schrumpfen und den Platz teilen */
                # min-width:0;        /* WICHTIG: min-content Schranke aufheben */
                # width:auto;         /* überschreibt evtl. alte width:100%-Regeln */
              }
              
                .tab-group > .custom-tab{
                    order: 1;                /* nach dem Icon */
                    flex: 0 0 auto;          /* natürliche Breite */
                }
                
              # .custom-tab{ flex:0 0 auto; } /* Tabs behalten natürliche Breite */
              
              /* Premium NICHT nach rechts schieben – im Flow lassen */
              .header-bar .premium-right{
                position: static !important;
                # margin-left:0 !important;
                right:auto !important; 
                top:auto !important;
                order:2;
                flex:0 0 auto;
              }
  
              .page-title{ margin: 4px 0 0; }
            }



            /* Premium-Rahmenfarben an Buttons (Battery/Heater/Wallbox) */
            .custom-tab.battery-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.battery-premium-locked { border-color: #e74c3c !important; }
            .custom-tab.battery-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.battery-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }

            .custom-tab.heater-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.heater-premium-locked { border-color: #e74c3c !important; }
            .custom-tab.heater-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.heater-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }

            .custom-tab.wallbox-premium-ok { border-color: #27ae60 !important; }
            .custom-tab.wallbox-premium-locked { border-color: #e74c3c !important; }
            .custom-tab.wallbox-premium-ok.custom-tab-selected { border-color: #27ae60 !important; }
            .custom-tab.wallbox-premium-locked.custom-tab-selected { border-color: #e74c3c !important; }



            /* Footer metrics — row on desktop, vertical stack on phones */
            .footer-stats {
              display: flex;
              flex-wrap: wrap;
              justify-content: center;
              gap: 40px;
              margin-top: 20px;
              width: 100%;
            }
            .footer-stat { font-weight: bold; text-align: center; }
            @media (max-width: 680px) {
              .footer-stats { flex-direction: column; align-items: center; gap: 8px; }
              .footer-stat { flex: 0 0 auto; width: 100%; }
            }

            /* Grundabstand für alle Seiten */
            .content-area {
              margin-top: 0;                 /* kein Margin ➜ kein Collapsing */
              padding: 12px 16px 16px;       /* dezenter Innenabstand überall */
              box-sizing: border-box;        /* Padding zählt zur Breite */
            }
            
            // html, body { border: 0 !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
            <script src="oauth/config.js"></script>
            <script>
                (function(){
                  function callFinish(url){ try{ fetch(url,{credentials:'include'}); }catch(_){} }

                  // Debug-Overlay
                  function dbg(s){ try{ document.getElementById('poll-debug').textContent = s; }catch(_){} }

                  const MOBILE_POLLING_ENABLED =
                    (typeof window.__MOBILE_POLLING__ !== 'undefined') ? !!window.__MOBILE_POLLING__ : true;
                  dbg('poll-enabled=' + MOBILE_POLLING_ENABLED);

                  let oauthPollTimer=null, oauthPollStarted=false, oauthPollDeadline=0;

                  function startMobilePolling(){
                    if (!MOBILE_POLLING_ENABLED || oauthPollStarted) return;
                    oauthPollStarted = true;
                    oauthPollDeadline = Date.now() + 2*60*1000;
                    dbg('poll:start');

                    function pollOnce(){
                      if (Date.now() > oauthPollDeadline){ stopMobilePolling(); dbg('poll:timeout'); return; }
                      dbg('poll:tick');
                      fetch('oauth/pending?t=' + Date.now(), { credentials: 'include', cache: 'no-store' })
                        .then(r=>r.ok?r.json():Promise.reject(new Error('http '+r.status)))
                        .then(j=>{
                          dbg('poll:' + JSON.stringify(j));
                          if (!j || !j.status) return;
                          if (j.status === 'ok' && j.grant){
                            stopMobilePolling();
                            callFinish('oauth/finish?grant=' + encodeURIComponent(j.grant));
                            try{ location.hash='premium=ok'; }catch(_){}
                          } else if (j.status === 'error'){
                            if (j.code === 'pending_proxy_exception'){ return; } // weiterpoll'en
                            stopMobilePolling();
                            callFinish('oauth/finish?error=' + encodeURIComponent(j.code || 'unknown'));
                            try{ location.hash='premium_error=' + encodeURIComponent(j.code || 'unknown'); }catch(_){}
                          }
                        })
                        .catch(e=>{ dbg('poll:err ' + e); });
                    }
                    oauthPollTimer = setInterval(pollOnce, 1500);
                    pollOnce();
                  }
                  function stopMobilePolling(){ try{ if(oauthPollTimer) clearInterval(oauthPollTimer); }catch(_){}
                    oauthPollTimer=null;
                  }

                  document.addEventListener('click', function(ev){
                    var t = ev.target;
                    if (t && (t.id === 'btn-premium' || t.id === 'btn-premium-upsell')){
                      ev.preventDefault();
                      fetch('oauth/link',{credentials:'include'})
                        .then(r=>r.json())
                        .then(j=>{ try{ window.open(j.url,'_blank'); }catch(_){}; try{ startMobilePolling(); }catch(_){}; });
                    }
                  });

                  // Ergebnis entgegennehmen -> Add-on intern abschließen -> Toast
                  function handlePayload(data){
                    if (!data || data.type !== 'pvmining:oauth') return;
                    if (data.status === 'ok' && data.grant) {
                      callFinish('oauth/finish?grant=' + encodeURIComponent(data.grant));
                      return;
                    }
                    if (data.status === 'error') {
                      callFinish('oauth/finish?error=' + encodeURIComponent(data.code || 'unknown'));
                      return;
                    }
                  }
                  window.addEventListener('message', function(ev){ try { handlePayload(ev && ev.data); } catch(_){} });

                  // Hash-Fallback (falls der Popup-Tab opener.hash setzt)
                  function handleHash(){
                    var h = (location.hash || '').slice(1);
                    if (!h) return;
                    var qs = new URLSearchParams(h);
                    if (qs.has('grant')) {
                      callFinish('oauth/finish?grant=' + encodeURIComponent(qs.get('grant') || ''));
                    } else if (qs.has('premium_error')) {
                      callFinish('oauth/finish?error=' + encodeURIComponent(qs.get('premium_error') || 'unknown'));
                    }
                    try { history.replaceState(null, '', location.pathname + location.search + '#'); } catch(_){}
                  }
                  window.addEventListener('hashchange', handleHash);
                  handleHash();
                })();
            </script>
            # <script>
            #     /* Synchronisiere den Seitenhintergrund mit #app-root, damit kein weißer 1px-Streifen bleibt */
            #     (function syncBodyBg(){
            #       function apply() {
            #         try {
            #           var root = document.getElementById('app-root');
            #           if (!root) return;
            #           // berechnete Hintergrundfarbe des App-Containers lesen
            #           var bg = getComputedStyle(root).backgroundColor;
            #           if (bg) {
            #             document.body.style.background = bg;
            #             document.documentElement.style.background = bg; // <html>
            #           }
            #         } catch (_) {}
            #       }
            #       if (document.readyState === 'loading') {
            #         document.addEventListener('DOMContentLoaded', apply);
            #       } else {
            #         apply();
            #       }
            #     })();
            # </script>
        </footer>

        <div id="poll-debug" style="position:fixed;bottom:8px;left:8px;font:12px monospace;opacity:.6"></div>

    </body>
</html>
'''

app.layout = page_wrap([
    dcc.Store(id="active-tab", data="dashboard"),
    dcc.Store(id="premium-enabled", data={"enabled": is_premium_enabled()}),
    dcc.Store(id="prio-order", storage_type="local"),
    dcc.Store(id="flash-visible-until", data=0),
    dcc.Interval(id="flash-poll", interval=2000, n_intervals=0),
    dcc.Location(id="url", refresh=False),
    # html.Div(id="flash-area", style={"margin":"8px 0"}),
    html.Div(
        id="flash-area",
        style={
            "margin": "0",                         # keine top-margin (verhindert weißen Balken)
            "padding": "8px 0",                    # optischer Abstand statt margin
            "backgroundColor": ui_background_color(),  # nimmt deine Config-Farbe
            "zIndex": 10,
        },
    ),


    # NEU: globaler Engine-Timer (unabhängig vom Tab)
    dcc.Interval(id="planner-engine", interval=10_000, n_intervals=0),  # alle 10s
    html.Div(id="planner-heartbeat", style={"display": "none"}),        # Dummy-Output

    html.Div([
        # html.Img(src=f"{prefix}config-icon", className="header-icon"),
        html.A(
            html.Img(
                src=f"{prefix}config-icon",
                className="header-icon",
                alt="BitcoinSolution.at"
            ),
            href="https://www.bitcoinsolution.at",
            target="_blank",
            rel="noopener noreferrer",
            id="brand-link",
            style={"display": "block"}
        ),

        # zentrierte Tab-Gruppe
        html.Div([
            html.Button("Dashboard", id="btn-dashboard", n_clicks=0, className="custom-tab custom-tab-selected", **{"data-tab": "dashboard"}),
            html.Button("Sensors", id="btn-sensors", n_clicks=0, className="custom-tab", **{"data-tab": "sensors"}),
            html.Button("Miners", id="btn-miners", n_clicks=0, className="custom-tab", **{"data-tab": "miners"}),
            html.Button("Electricity", id="btn-electricity", n_clicks=0, className="custom-tab", **{"data-tab": "electricity"}),
            html.Button("Battery", id="btn-battery", n_clicks=0, className="custom-tab", **{"data-tab": "battery"}),
            html.Button("Water Heater", id="btn-heater", n_clicks=0, className="custom-tab", **{"data-tab": "heater"}),
            html.Button("Wall-Box", id="btn-wallbox", n_clicks=0, className="custom-tab", **{"data-tab": "wallbox"}),
            html.Button("Settings", id="btn-settings", n_clicks=0, className="custom-tab", **{"data-tab": "settings"}),
            html.Button("Dev", id="btn-dev", n_clicks=0, className="custom-tab", style=({} if SHOW_DEV_TAB else {"display": "none"})),
        ], className="tab-group"),

        # Premium ganz rechts
        html.Button("Activate Premium", id="btn-premium",
                    n_clicks=0, className="custom-tab premium-btn premium-right"),
    ], id="tab-buttons", className="header-bar",
        style={"backgroundColor": ui_background_color(), "padding": "6px 10px"}),

    html.Div(
        id="tabs-content",
        className="content-area",
        style={
            "backgroundColor": ui_background_color(),
            "minHeight": "calc(100vh - 120px)",  # schrumpft nicht weg
            "paddingBottom": "16px",
        },
    ),
])

@app.callback(
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