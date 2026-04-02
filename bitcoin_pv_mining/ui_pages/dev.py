import os
import requests

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from services.utils import load_state
from services.license import set_token, verify_license, is_premium_enabled
try:
    from services.dev_mock import collect_specs, get_values, is_enabled as mock_is_enabled, set_config as set_mock_config
    MOCK_AVAILABLE = True
except Exception:
    MOCK_AVAILABLE = False

    def collect_specs():
        return []

    def get_values():
        return {}

    def mock_is_enabled():
        return False

    def set_mock_config(enabled, values):
        return None

LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")


def _install_id() -> str:
    try:
        st = load_state() or {}
        return st.get("install_id", "unknown-install")
    except Exception:
        return "unknown-install"


def _mock_table():
    specs = collect_specs()
    values = get_values()

    if not MOCK_AVAILABLE:
        return html.Div(
            "Mock data support is not installed in this build. The addon runs with real Home Assistant data only.",
            className="settings-subtle-text",
        )

    rows = []
    for spec in specs:
        key = spec["key"]
        current = values.get(key, spec.get("default", ""))
        rows.append(
            html.Tr(
                [
                    html.Td(spec["label"], style={"padding": "8px 10px", "fontWeight": "600", "verticalAlign": "top"}),
                    html.Td(
                        html.Div(
                            [
                                html.Code(key, style={"fontSize": "12px", "wordBreak": "break-all"}),
                                html.Div(
                                    spec.get("mapped_entity") or "No real entity mapped",
                                    className="settings-subtle-text",
                                    style={"marginTop": "6px", "fontSize": "12px", "wordBreak": "break-all"},
                                ),
                            ]
                        ),
                        style={"padding": "8px 10px", "opacity": 0.8, "verticalAlign": "top"},
                    ),
                    html.Td(
                        dcc.Input(
                            id={"type": "dev-mock-value", "key": key},
                            type="text",
                            value=str(current),
                            placeholder=str(spec.get("default", "")),
                            style={"width": "100%"},
                        ),
                        style={"padding": "8px 10px", "minWidth": "220px"},
                    ),
                ]
            )
        )

    return html.Div(
        [
            html.Div(
                "When mock data is ON, configured mock values override real sensor values. Leave a row empty to fall back to the real sensor.",
                className="settings-subtle-text",
                style={"marginBottom": "12px"},
            ),
            html.Div(
                [
                    html.Label("Mock data", style={"marginBottom": "8px"}),
                    dcc.Slider(
                        id="dev-mock-enabled",
                        min=0,
                        max=1,
                        step=1,
                        value=1 if mock_is_enabled() else 0,
                        marks={0: "OFF", 1: "ON"},
                        tooltip={"always_visible": False},
                    ),
                ],
                style={"marginBottom": "16px"},
            ),
            html.Div(
                [
                    html.Button("Save mock data", id="dev-mock-save", n_clicks=0, className="custom-tab"),
                    html.Span(id="dev-mock-status", className="settings-status", style={"marginLeft": "10px"}),
                ],
                className="settings-page-actions",
                style={"marginTop": "0", "marginBottom": "14px"},
            ),
            html.Div(
                [
                    html.Table(
                        [
                            html.Thead(
                                html.Tr(
                                    [
                                        html.Th("Label", style={"textAlign": "left", "padding": "8px 10px"}),
                                        html.Th("Sensor / key", style={"textAlign": "left", "padding": "8px 10px"}),
                                        html.Th("Mock value", style={"textAlign": "left", "padding": "8px 10px"}),
                                    ]
                                )
                            ),
                            html.Tbody(rows),
                        ],
                        style={"width": "100%", "borderCollapse": "collapse"},
                    )
                ],
                style={"overflowX": "auto"},
            ),
        ]
    )


def layout():
    ins = _install_id()
    return html.Div(
        [
            html.H2("Developer tools", className="settings-title", style={"marginBottom": "18px"}),

            html.Div(
                [
                    html.H3("Mock data", className="settings-section-title"),
                    html.Div(_mock_table(), className="settings-card"),
                ],
                className="settings-section",
            ),

            html.Div(
                [
                    html.H3("Install / license tools", className="settings-section-title"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Install ID"),
                                    dcc.Input(
                                        id="dev-install-id",
                                        type="text",
                                        value=ins,
                                        readOnly=True,
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"marginBottom": "12px"},
                            ),

                            html.Hr(),

                            html.H3("1) Grant holen (Server → pending_set.php)"),
                            html.Div(
                                [
                                    html.Label("Admin API key"),
                                    dcc.Input(
                                        id="dev-admin-key",
                                        type="password",
                                        className="dev-plain-input",
                                        value="",
                                        placeholder="ADMIN_API_KEY",
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"marginBottom": "8px"},
                            ),

                            html.Div(
                                [
                                    html.Button("Get grant", id="dev-btn-get-grant", n_clicks=0, className="custom-tab"),
                                    html.Span(id="dev-get-grant-status", style={"marginLeft": "10px", "opacity": 0.8}),
                                ],
                                style={"marginBottom": "8px"},
                            ),

                            html.Div(
                                [
                                    html.Label("Grant"),
                                    dcc.Input(id="dev-grant", type="text", value="", style={"width": "100%"}),
                                ],
                                style={"marginBottom": "6px"},
                            ),

                            html.Details(
                                [
                                    html.Summary("Raw response"),
                                    html.Pre(id="dev-grant-raw", style={"whiteSpace": "pre-wrap"}),
                                ],
                                open=False,
                            ),

                            html.Hr(),

                            html.H3("2) Grant im Add-on einlösen"),
                            html.Div(
                                [
                                    html.Button("Redeem grant now", id="dev-btn-redeem", n_clicks=0, className="custom-tab"),
                                    html.Span(id="dev-redeem-status", style={"marginLeft": "10px", "fontWeight": "bold"}),
                                ],
                                style={"marginBottom": "12px"},
                            ),

                            html.Hr(),

                            html.H3("3) Premium Token leeren"),
                            html.Div(
                                [
                                    html.Button("Clear token", id="dev-btn-clear-token", n_clicks=0, className="custom-tab"),
                                    html.Span(id="dev-clear-status", style={"marginLeft": "10px", "opacity": 0.8}),
                                ]
                            ),

                            html.Hr(),

                            html.Div(id="dev-current-status", style={"marginTop": "8px", "opacity": 0.85}),
                            dcc.Interval(id="dev-status-tick", interval=2000, n_intervals=0),
                        ],
                        className="settings-card",
                    ),
                ],
                className="settings-section",
            ),
        ],
        className="settings-page",
    )


def register_callbacks(app):
    @app.callback(
        Output("dev-mock-status", "children"),
        Input("dev-mock-save", "n_clicks"),
        State("dev-mock-enabled", "value"),
        State({"type": "dev-mock-value", "key": ALL}, "id"),
        State({"type": "dev-mock-value", "key": ALL}, "value"),
        prevent_initial_call=True,
    )
    def _save_mock(n, enabled, ids, values):
        if not n:
            raise PreventUpdate
        if not MOCK_AVAILABLE:
            return "Mock data support is not installed in this build."

        payload = {}
        for ident, value in zip(ids or [], values or []):
            key = (ident or {}).get("key")
            if key is None:
                continue
            text = "" if value is None else str(value).strip()
            if text:
                payload[key] = text

        set_mock_config(bool(enabled), payload)
        return f"Mock data saved. Mode={'ON' if enabled else 'OFF'}."

    @app.callback(
        Output("dev-grant", "value"),
        Output("dev-grant-raw", "children"),
        Output("dev-get-grant-status", "children"),
        Input("dev-btn-get-grant", "n_clicks"),
        State("dev-admin-key", "value"),
        State("dev-install-id", "value"),
        prevent_initial_call=True,
    )
    def _get_grant(n, key, install_id):
        if not n:
            raise PreventUpdate
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
        prevent_initial_call=True,
    )
    def _redeem(n, grant, install_id):
        if not n:
            raise PreventUpdate
        grant = (grant or "").strip()
        if not grant:
            return "No grant"
        try:
            r = requests.post(
                f"{LICENSE_BASE_URL}/redeem.php",
                json={"grant": grant, "install_id": install_id},
                timeout=10,
            )
            js = {}
            try:
                js = r.json()
            except Exception:
                pass

            if js.get("ok") and js.get("token"):
                set_token(js["token"])
                verify_license()
                return f"Redeemed. premium_enabled={is_premium_enabled()}"
            return f"Redeem failed: {js or r.text}"
        except Exception as e:
            return f"Redeem exception: {e}"

    @app.callback(
        Output("dev-clear-status", "children"),
        Input("dev-btn-clear-token", "n_clicks"),
        prevent_initial_call=True,
    )
    def _clear(n):
        if not n:
            raise PreventUpdate
        try:
            set_token("")
            verify_license()
            return "Token cleared."
        except Exception as e:
            return f"ERR: {e}"

    @app.callback(
        Output("dev-current-status", "children"),
        Input("dev-status-tick", "n_intervals"),
        State("dev-mock-enabled", "value"),
        prevent_initial_call=False,
    )
    def _show_status(_n, mock_enabled):
        try:
            return f"Current premium_enabled={is_premium_enabled()} | mock_data={'ON' if mock_enabled else 'OFF'}"
        except Exception:
            return f"Current premium_enabled=? | mock_data={'ON' if mock_enabled else 'OFF'}"
