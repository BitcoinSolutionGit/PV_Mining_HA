# ui_pages/dev.py
import os, json, requests
from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State

from services.utils import load_state
from services.license import set_token, verify_license, is_premium_enabled

LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")


def _install_id() -> str:
    try:
        st = load_state() or {}
        return st.get("install_id", "unknown-install")
    except Exception:
        return "unknown-install"


def layout():
    ins = _install_id()
    return html.Div([
        html.H2("Developer tools"),

        html.Div([
            html.Label("Install ID"),
            dcc.Input(id="dev-install-id", type="text", value=ins, readOnly=True,
                      style={"width":"100%"}),
        ], style={"marginBottom":"12px"}),

        html.Hr(),

        html.H3("1) Grant holen (Server → pending_set.php)"),
        html.Div([
            html.Label("Admin API key"),
            dcc.Input(id="dev-admin-key", type="password", value="",
                      placeholder="ADMIN_API_KEY", style={"width":"100%"}),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Button("Get grant", id="dev-btn-get-grant", n_clicks=0, className="custom-tab"),
            html.Span(id="dev-get-grant-status", style={"marginLeft":"10px","opacity":0.8}),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Label("Grant"),
            dcc.Input(id="dev-grant", type="text", value="", style={"width":"100%"}),
        ], style={"marginBottom":"6px"}),

        html.Details([
            html.Summary("Raw response"),
            html.Pre(id="dev-grant-raw", style={"whiteSpace":"pre-wrap"})
        ], open=False),

        html.Hr(),

        html.H3("2) Grant im Add-on einlösen"),
        html.Div([
            html.Button("Redeem grant now", id="dev-btn-redeem", n_clicks=0, className="custom-tab"),
            html.Span(id="dev-redeem-status", style={"marginLeft":"10px","fontWeight":"bold"}),
        ], style={"marginBottom":"12px"}),

        html.Hr(),

        html.H3("3) Premium Token leeren"),
        html.Div([
            html.Button("Clear token", id="dev-btn-clear-token", n_clicks=0, className="custom-tab"),
            html.Span(id="dev-clear-status", style={"marginLeft":"10px","opacity":0.8}),
        ]),

        html.Hr(),

        html.Div(id="dev-current-status", style={"marginTop":"8px","opacity":0.85}),
        dcc.Interval(id="dev-status-tick", interval=2000, n_intervals=0),
    ], style={"border":"2px dashed #999","borderRadius":"8px","padding":"12px","background":"#fcfcfc"})


def register_callbacks(app):
    @app.callback(
        Output("dev-grant", "value"),
        Output("dev-grant-raw", "children"),
        Output("dev-get-grant-status", "children"),
        Input("dev-btn-get-grant", "n_clicks"),
        State("dev-admin-key", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True
    )
    def _get_grant(n, key, install_id):
        if not n:
            raise RuntimeError
        key = (key or "").strip()
        if not key:
            return no_update, no_update, "Missing ADMIN_API_KEY"
        try:
            url = (
                f"{LICENSE_BASE_URL}/admin/pending_set.php"
                f"?key={key}&install_id={install_id}&status=ok&create=1"
            )
            r = requests.get(url, timeout=10)
            txt = r.text
            try:
                js = r.json()
            except Exception:
                js = {}
            grant = js.get("grant") or ""
            status = "OK" if (r.ok and grant) else f"HTTP {r.status_code}"
            return grant, txt, status
        except Exception as e:
            return no_update, no_update, f"ERR: {e}"

    @app.callback(
        Output("dev-redeem-status", "children"),
        Input("dev-btn-redeem", "n_clicks"),
        State("dev-grant", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True
    )
    def _redeem(n, grant, install_id):
        if not n:
            raise RuntimeError
        grant = (grant or "").strip()
        if not grant:
            return "No grant"
        try:
            r = requests.post(
                f"{LICENSE_BASE_URL}/redeem.php",
                json={"grant": grant, "install_id": install_id},
                timeout=10
            )
            js = {}
            try:
                js = r.json()
            except Exception:
                pass

            if js.get("ok") and js.get("token"):
                # Sofort übernehmen
                set_token(js["token"])
                verify_license()
                return f"Redeemed. premium_enabled={is_premium_enabled()}"
            else:
                return f"Redeem failed: {js or r.text}"
        except Exception as e:
            return f"Redeem exception: {e}"

    @app.callback(
        Output("dev-clear-status", "children"),
        Input("dev-btn-clear-token", "n_clicks"),
        prevent_initial_call=True
    )
    def _clear(n):
        if not n:
            raise RuntimeError
        try:
            set_token("")
            verify_license()
            return "Token cleared."
        except Exception as e:
            return f"ERR: {e}"

    @app.callback(
        Output("dev-current-status", "children"),
        Input("dev-status-tick", "n_intervals"),
        prevent_initial_call=False
    )
    def _show_status(_n):
        try:
            return f"Current premium_enabled={is_premium_enabled()}"
        except Exception:
            return "Current premium_enabled=?"
