# ui_pages/dev.py
import os, requests
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.utils import load_state, save_state, iso_now
from services.license import set_token, verify_license, is_premium_enabled

LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")

def layout():
    return html.Div([
        html.H3("Developer Tools"),
        html.P("This page is visible only when feature_flags.show_dev_tab = true in pv_mining_local_config.yaml."),

        html.Div([
            html.Button("Get install_id", id="dev-btn-install", className="custom-tab"),
            dcc.Input(id="dev-install-id", value="", readOnly=True, style={"width":"420px","marginLeft":"8px"}),
        ], style={"marginBottom":"10px"}),

        html.Hr(),

        html.Div([
            html.Label("Admin API key (not stored)"),
            dcc.Input(id="dev-admin-key", type="password", value="", style={"width":"520px"}),
        ], style={"margin":"6px 0"}),

        html.Div([
            html.Button("Request DEV grant", id="dev-btn-grant", className="custom-tab"),
            dcc.Input(id="dev-grant", value="", style={"width":"520px","marginLeft":"8px"}),
        ], style={"margin":"6px 0"}),

        html.Div(id="dev-grant-status", style={"marginTop":"6px","opacity":0.8}),
        html.Hr(),

        html.Button("Redeem grant (apply in addon)", id="dev-btn-redeem", className="custom-tab"),
        html.Div(id="dev-redeem-status", style={"marginTop":"8px","fontWeight":"bold"}),

    ], style={"border":"2px dashed #999","borderRadius":"8px","padding":"10px","background":"#fcfcfc"})

def register_callbacks(app):

    # kleine lokale Flash-Hilfe (identisch zum Verhalten in main)
    def _flash(level: str, code: str) -> None:
        try:
            st = load_state()
            st["ui_flash"] = {"level": level, "code": code, "ts": iso_now()}
            save_state(st)
        except Exception as e:
            print("[DEV] flash error:", e, flush=True)

    @app.callback(
        Output("dev-install-id", "value"),
        Input("dev-btn-install", "n_clicks"),
        prevent_initial_call=True
    )
    def _get_install_id(_n):
        st = load_state()
        return st.get("install_id", "unknown-install")

    @app.callback(
        Output("dev-grant", "value"),
        Output("dev-grant-status", "children"),
        Input("dev-btn-grant", "n_clicks"),
        State("dev-admin-key", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True
    )
    def _request_grant(_n, admin_key, install_id):
        if not admin_key or not install_id:
            return "", "Need Admin key AND install_id."
        try:
            url = (f"{LICENSE_BASE_URL}/admin/pending_set.php"
                   f"?key={requests.utils.quote(admin_key)}"
                   f"&install_id={requests.utils.quote(install_id)}"
                   f"&status=ok&create=1")
            r = requests.get(url, timeout=10)
            j = r.json()
            if j.get("ok") and j.get("grant"):
                return j["grant"], "Grant created."
            return "", f"Failed: {j}"
        except Exception as e:
            return "", f"Error: {e!r}"

    @app.callback(
        Output("dev-redeem-status", "children"),
        Input("dev-btn-redeem", "n_clicks"),
        State("dev-grant", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True
    )
    def _redeem(_n, grant, install_id):
        if not grant:
            return "No grant."
        try:
            r = requests.post(f"{LICENSE_BASE_URL}/redeem.php",
                              json={"grant": grant, "install_id": install_id or ""},
                              timeout=10)
            j = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            if j.get("ok") and j.get("token"):
                # wende Token lokal an + Lizenz frisch prüfen
                set_token(j["token"])
                verify_license()

                # trigger Toast in bestehendem flash-poll
                _flash("ok", "premium_ok")

                # zur Sicherheit ausgeben, was premium jetzt sagt
                return f"Redeemed. premium_enabled={is_premium_enabled()}"
            else:
                _flash("error", "redeem_failed")
                return f"Redeem failed: {j}"
        except Exception as e:
            _flash("error", "redeem_exception")
            return f"Redeem exception: {e!r}"
