# ui_pages/dev.py
import os
import urllib.parse
import requests

import dash
from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State

from services.utils import load_state
from services.license import set_token, verify_license, is_premium_enabled

LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")

def layout():
    return html.Div([
        html.H2("Developer Tools"),
        html.Div("This page is visible only when feature_flags.show_dev_tab = true in pv_mining_local_config.yaml.",
                 style={"opacity": 0.7, "marginBottom": "12px"}),

        # --- install_id row ---
        html.Div([
            html.Button("Get install_id", id="dev-get-install", className="custom-tab"),
            dcc.Input(id="dev-install-id", type="text", readOnly=True, style={"marginLeft":"10px", "minWidth":"420px"}),
        ], style={"display":"flex","alignItems":"center","gap":"8px"}),

        html.Hr(),

        # --- Admin key + request grant ---
        html.Div([
            html.Label("Admin API key (not stored)"),
            dcc.Input(id="dev-admin-key", type="password", style={"minWidth":"420px"}),
        ], style={"marginTop":"6px"}),

        html.Div([
            html.Button("Request DEV grant", id="dev-request-grant", className="custom-tab"),
            dcc.Input(id="dev-grant", type="text", placeholder="grant will appear here…",
                      style={"marginLeft":"10px","minWidth":"420px"}),
        ], style={"display":"flex","alignItems":"center","gap":"8px","marginTop":"8px"}),

        html.Div(id="dev-admin-status", style={"marginTop":"6px","fontWeight":"bold"}),

        html.Hr(),

        # --- Redeem grant locally ---
        html.Div([
            html.Button("Redeem grant (apply in addon)", id="dev-redeem", className="custom-tab"),
            html.Span(id="dev-redeem-status", style={"marginLeft":"10px","fontWeight":"bold"}),
        ], style={"display":"flex","alignItems":"center","gap":"8px","marginTop":"6px"}),

        # one-shot to auto-fill install_id on open
        dcc.Interval(id="dev-once", interval=1, n_intervals=0, max_intervals=1),
    ], style={"maxWidth":"900px"})

def register_callbacks(app):

    @app.callback(
        Output("dev-install-id", "value"),
        Input("dev-get-install", "n_clicks"),
        Input("dev-once", "n_intervals"),
        prevent_initial_call=False
    )
    def _fill_install_id(_btn, _once):
        try:
            install_id = (load_state() or {}).get("install_id") or ""
            return install_id
        except Exception:
            return ""

    @app.callback(
        Output("dev-grant", "value"),
        Output("dev-admin-status", "children"),
        Input("dev-request-grant", "n_clicks"),
        State("dev-install-id", "value"),
        State("dev-admin-key", "value"),
        prevent_initial_call=True
    )
    def _request_grant(n, install_id, admin_key):
        if not n:
            raise dash.exceptions.PreventUpdate
        if not (install_id and admin_key):
            return no_update, "Please provide install_id and Admin API key."

        try:
            params = {
                "key": admin_key,
                "install_id": install_id,
                "status": "ok",
                "create": "1",
            }
            url = f"{LICENSE_BASE_URL}/admin/pending_set.php?" + urllib.parse.urlencode(params, safe="")
            # bewusst keine Ausgabe des Keys ins Log
            headers = {"User-Agent": "pv-mining-addon/dev-panel", "Accept": "application/json"}
            r = requests.get(url, headers=headers, timeout=10)
            js = {}
            if r.headers.get("content-type","").startswith("application/json"):
                js = r.json()
            if r.ok and js.get("ok") and js.get("grant"):
                return js["grant"], "Grant created."
            # Fehlerfall
            err = js.get("error") or js.get("err") or f"http {r.status_code}"
            return no_update, f"Request failed: {err}"
        except Exception as e:
            return no_update, f"Exception: {e}"

    @app.callback(
        Output("dev-redeem-status", "children"),
        Output("premium-enabled", "data", allow_duplicate=True),
        Input("dev-redeem", "n_clicks"),
        State("dev-grant", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True
    )
    def _redeem(n, grant, install_id):
        if not n:
            raise dash.exceptions.PreventUpdate
        if not grant:
            return "Please provide a grant code.", no_update
        try:
            r = requests.post(f"{LICENSE_BASE_URL}/redeem.php",
                              json={"grant": str(grant), "install_id": str(install_id or "")},
                              headers={"Accept":"application/json"},
                              timeout=12)
            js = {}
            if r.headers.get("content-type","").startswith("application/json"):
                js = r.json()

            if r.ok and js.get("ok") and js.get("token"):
                # lokal aktivieren
                set_token(js["token"])
                verify_license()
                return "Premium activated.", {"enabled": bool(is_premium_enabled())}

            err = js.get("err") or js.get("error") or f"http {r.status_code}"
            return f"Redeem failed: {err}", no_update

        except Exception as e:
            return f"Exception: {e}", no_update
