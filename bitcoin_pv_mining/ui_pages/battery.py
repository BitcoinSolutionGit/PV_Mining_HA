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

def _row():
    return {"display":"flex","alignItems":"center","gap":"8px","flexWrap":"wrap","marginBottom":"10px"}


def layout():
    # gespeicherte Auswahl:
    cap  = bat_get("capacity_entity", "")
    soc  = bat_get("soc_entity", "")
    vdc  = bat_get("voltage_entity", "")
    idc  = bat_get("current_entity", "")
    temp = bat_get("temperature_entity", "")
    pwr  = bat_get("power_entity", "")

    sensor_opts = _sensor_options()

    return html.Div([
        html.H2("Battery"),

        # --- Kapazität ---
        html.Div([
            html.Label("Capacity sensor (kWh, optional)", style={"marginLeft":"16px"}),
            dcc.Dropdown(id="bat-cap-entity", options=sensor_opts, value=(cap or None),
                         placeholder="Select sensor.…", style={"minWidth":"360px"}),
            html.Span(id="bat-cap-val", style={"marginLeft":"12px","opacity":0.8}),  # Live-Anzeige
        ], _row()),

        # --- SoC ---
        html.Div([
            html.Label("SOC sensor (%)"),
            dcc.Dropdown(id="bat-soc-entity", options=sensor_opts, value=(soc or None),
                         placeholder="Select sensor.…", style={"minWidth":"420px"}),
            html.Span(id="bat-soc-val", style={"marginLeft":"12px","opacity":0.8}),
        ], _row()),

        # --- Spannung ---
        html.Div([
            html.Label("DC voltage (V)"),
            dcc.Dropdown(id="bat-vdc-entity", options=sensor_opts, value=(vdc or None),
                         placeholder="Select sensor.…", style={"minWidth":"360px"}),
            html.Span(id="bat-vdc-val", style={"marginLeft":"12px","opacity":0.8}),
        ], _row()),

        # --- Strom ---
        html.Div([
            html.Label("DC current (A)", style={"marginLeft":"18px"}),
            dcc.Dropdown(id="bat-idc-entity", options=sensor_opts, value=(idc or None),
                         placeholder="Select sensor.…", style={"minWidth":"360px"}),
            html.Span(id="bat-idc-val", style={"marginLeft":"12px","opacity":0.8}),
        ], _row()),

        # --- Temperatur  ---
        html.Div([
            html.Label("Temperature (°C)"),
            dcc.Dropdown(id="bat-temp-entity", options=sensor_opts, value=(temp or None),
                         placeholder="Select sensor.…", style={"minWidth":"360px"}),
            html.Span(id="bat-temp-val", style={"marginLeft":"12px","opacity":0.8}),
        ], _row()),

        # --- Leistung ---
            html.Div([
            html.Label("Power (kW, optional)", style={"marginLeft":"18px"}),
            dcc.Dropdown(id="bat-power-entity", options=sensor_opts, value=(pwr or None),
                         placeholder="Select sensor.…", style={"minWidth":"360px"}),
            html.Span(id="bat-power-val", style={"marginLeft":"12px","opacity":0.8}),
        ], _row()),

        html.Button("Save", id="bat-save", className="custom-tab"),
        html.Span(id="bat-save-status", style={"marginLeft":"8px","color":"green"}),

        # einmal Options refresh + Livewerte
        dcc.Interval(id="bat-scan", interval=1500, n_intervals=0, max_intervals=1),
        dcc.Interval(id="bat-live", interval=5000, n_intervals=0),
    ])



def register_callbacks(app):

    @app.callback(
        Output("bat-save-status", "children"),
        Input("bat-save", "n_clicks"),
        State("bat-cap-entity", "value"),
        State("bat-soc-entity", "value"),
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        State("bat-power-entity", "value"),
        prevent_initial_call=True
    )
    def _save(n, cap, soc, vdc, idc, temp, pwr):
        if not n:
            raise dash.exceptions.PreventUpdate
        bat_set(
            capacity_entity=cap or "",
            soc_entity=soc or "",
            voltage_entity=vdc or "",
            current_entity=idc or "",
            temperature_entity=temp or "",
            power_entity=pwr or "",
        )
        return "Saved."


    @app.callback(
        Output("bat-cap-entity", "options"),
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
        return opts, opts, opts, opts, opts, opts

    @app.callback(
        Output("bat-cap-val",  "children"),
        Output("bat-soc-val",  "children"),
        Output("bat-vdc-val",  "children"),
        Output("bat-idc-val",  "children"),
        Output("bat-temp-val", "children"),
        Output("bat-power-val","children"),
        Input("bat-live", "n_intervals"),
        State("bat-cap-entity",  "value"),
        State("bat-soc-entity",  "value"),
        State("bat-vdc-entity",  "value"),
        State("bat-idc-entity",  "value"),
        State("bat-temp-entity", "value"),
        State("bat-power-entity","value"),
        prevent_initial_call=False
    )
    def _live(_tick, cap_ent, soc_ent, vdc_ent, idc_ent, temp_ent, pwr_ent):
        def val(eid, fmt, unit=""):
            try:
                v = get_sensor_value(eid) if eid else None
                return (fmt.format(float(v)) + unit) if v is not None else "—"
            except Exception:
                return "—"

        cap  = val(cap_ent,  "{:.2f}", " kWh")
        soc  = val(soc_ent,  "{:.1f}", " %")
        vdc  = val(vdc_ent,  "{:.2f}", " V")
        idc  = val(idc_ent,  "{:.2f}", " A")
        t    = val(temp_ent, "{:.1f}", " °C")
        pwr  = val(pwr_ent,  "{:.3f}", " kW")

        return cap, soc, vdc, idc, t, pwr
