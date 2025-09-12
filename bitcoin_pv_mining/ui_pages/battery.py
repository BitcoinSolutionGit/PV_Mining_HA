# ui_pages/battery.py
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.battery_store import get_var as bat_get, set_vars as bat_set
from services.ha_sensors import get_sensor_value, list_entities_by_domain
from services.license import is_premium_enabled
from ui_pages.common import footer_license

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def _sensor_options() -> list[dict]:
    """Alle sensor.* Entitäten als Dropdown-Options."""
    try:
        sensors = list_entities_by_domain("sensor")         # ['sensor.xyz', ...]
    except Exception:
        sensors = []
    return [{"label": s, "value": s} for s in sensors]

def layout():
    # gespeicherte Auswahl vorbefüllen
    soc      = bat_get("soc_entity", "")
    vdc      = bat_get("voltage_entity", "")
    idc      = bat_get("current_entity", "")
    temp     = bat_get("temperature_entity", "")
    pwr      = bat_get("power_entity", "")

    sensor_opts = _sensor_options()

    return html.Div([
        html.H2("Battery"),

        html.Div([
            html.Label("SOC sensor entity (%, e.g. sensor.battery_soc)"),
            dcc.Dropdown(id="bat-soc-entity", options=sensor_opts, value=(soc or None),
                         placeholder="Select sensor.…", persistence=True, persistence_type="memory"),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Label("DC voltage entity (V)"),
            dcc.Dropdown(id="bat-vdc-entity", options=sensor_opts, value=(vdc or None),
                         placeholder="Select sensor.…", persistence=True, persistence_type="memory"),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Label("DC current entity (A) (positive = charge, negative = discharge)"),
            dcc.Dropdown(id="bat-idc-entity", options=sensor_opts, value=(idc or None),
                         placeholder="Select sensor.…", persistence=True, persistence_type="memory"),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Label("Battery temperature entity (°C)"),
            dcc.Dropdown(id="bat-temp-entity", options=sensor_opts, value=(temp or None),
                         placeholder="Select sensor.…", persistence=True, persistence_type="memory"),
        ], style={"marginBottom":"8px"}),

        html.Div([
            html.Label("Battery power entity (kW, optional)"),
            dcc.Dropdown(id="bat-power-entity", options=sensor_opts, value=(pwr or None),
                         placeholder="Select sensor.…", persistence=True, persistence_type="memory"),
        ], style={"marginBottom":"12px"}),

        html.Button("Save", id="bat-save", className="custom-tab"),
        html.Span(id="bat-save-status", style={"marginLeft":"8px","color":"green"}),

        # einmaliges Nachladen der Options nach Mount (falls HA langsam ist)
        dcc.Interval(id="bat-scan", interval=1500, n_intervals=0, max_intervals=1),
    ])


def register_callbacks(app):
    @app.callback(
        Output("bat-save-status", "children"),
        Input("bat-save", "n_clicks"),
        State("bat-soc-entity", "value"),
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        State("bat-power-entity", "value"),
        prevent_initial_call=True
    )
    def _save(n, soc, vdc, idc, temp, pwr):
        if not n: raise dash.exceptions.PreventUpdate
        bat_set(
            soc_entity=soc or "",
            voltage_entity=vdc or "",
            current_entity=idc or "",
            temperature_entity=temp or "",
            power_entity=pwr or "",
        )
        return "Saved."

    # optional: nach Mount die Options noch einmal aus HA ziehen
    @app.callback(
        Output("bat-soc-entity", "options"),
        Output("bat-vdc-entity", "options"),
        Output("bat-idc-entity", "options"),
        Output("bat-temp-entity", "options"),
        Output("bat-power-entity", "options"),
        Input("bat-scan", "n_intervals"),
        prevent_initial_call=True
    )
    def _refresh_opts(_n):
        opts = _sensor_options()
        return opts, opts, opts, opts, opts
