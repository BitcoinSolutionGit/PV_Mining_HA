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

def _sensor_options():
    try:
        # Alle sensor.* anbieten
        return [{"label": e, "value": e} for e in list_entities_by_domain(("sensor",))]
    except Exception:
        return []

def layout():
    return html.Div([
        html.H2("Battery"),

        html.Div([
            html.Div([
                html.Label("Enabled"),
                dcc.Checklist(id="bat-enabled",
                              options=[{"label":" on","value":"on"}],
                              value=(["on"] if bat_get("enabled", False) else []))
            ], style={"marginRight":"16px"}),
            html.Div([
                html.Label("Mode (auto)"),
                dcc.Checklist(id="bat-mode",
                              options=[{"label":" on","value":"auto"}],
                              value=(["auto"] if (bat_get("mode","manual")=="auto") else []))
            ]),
        ], style={"display":"flex","gap":"16px","flexWrap":"wrap"}),

        html.Div([
            html.Label("Capacity (kWh)"),
            dcc.Input(id="bat-cap", type="number", step=0.1, value=_num(bat_get("capacity_kwh",11.0),11.0), style={"width":"120px"}),
            html.Span("  "),
            html.Label("Max charge power (kW)"),
            dcc.Input(id="bat-max-ch", type="number", step=0.1, value=_num(bat_get("max_charge_kw",3.0),3.0), style={"width":"120px"}),
            html.Span("  "),
            html.Label("Max discharge power (kW)"),
            dcc.Input(id="bat-max-disch", type="number", step=0.1, value=_num(bat_get("max_discharge_kw",3.0),3.0), style={"width":"120px"}),
        ], style={"display":"flex","gap":"10px","alignItems":"center","flexWrap":"wrap","marginTop":"8px"}),

        html.Hr(),

        # --- neue Sensor-Auswahl ---
        html.Div([
            html.Div([
                html.Label("SOC sensor (%, e.g. sensor.battery_soc)"),
                dcc.Dropdown(id="bat-soc-ent", options=_sensor_options(),
                             value=(bat_get("soc_entity","") or None), placeholder="Select sensor…")
            ], style={"flex":"1","minWidth":"240px"}),

            html.Div([
                html.Label("DC voltage sensor (V)"),
                dcc.Dropdown(id="bat-v-ent", options=_sensor_options(),
                             value=(bat_get("dc_voltage_entity","") or None), placeholder="Select sensor…")
            ], style={"flex":"1","minWidth":"240px","marginLeft":"10px"}),

            html.Div([
                html.Label("DC current sensor (A; + = charging)"),
                dcc.Dropdown(id="bat-i-ent", options=_sensor_options(),
                             value=(bat_get("dc_current_entity","") or None), placeholder="Select sensor…")
            ], style={"flex":"1","minWidth":"240px","marginLeft":"10px"}),

            html.Div([
                html.Label("Temperature sensor (°C, optional)"),
                dcc.Dropdown(id="bat-t-ent", options=_sensor_options(),
                             value=(bat_get("temperature_entity","") or None), placeholder="Select sensor…")
            ], style={"flex":"1","minWidth":"240px","marginLeft":"10px"}),
        ], style={"display":"flex","gap":"10px","flexWrap":"wrap","marginTop":"8px"}),

        html.Div([
            html.Label("Target SOC (%)"),
            dcc.Input(id="bat-target", type="number", step=1, value=_num(bat_get("target_soc",90.0),90.0), style={"width":"100px"}),
            html.Span("  "),
            html.Label("Reserve SOC (%)"),
            dcc.Input(id="bat-reserve", type="number", step=1, value=_num(bat_get("reserve_soc",20.0),20.0), style={"width":"100px"}),
            html.Span("  "),
            dcc.Checklist(id="bat-grid-charge",
                          options=[{"label":" Allow grid charge (policy)","value":"allow"}],
                          value=(["allow"] if bat_get("allow_grid_charge", False) else [])),
        ], style={"display":"flex","gap":"10px","alignItems":"center","flexWrap":"wrap","marginTop":"8px"}),

        html.Hr(),

        html.Div(id="bat-kpi-soc", style={"fontWeight":"bold"}),
        html.Div(id="bat-kpi-power", style={"marginTop":"4px"}),
        html.Div("Estimated charge power: up to {:.1f} kW".format(_num(bat_get("max_charge_kw",3.0),3.0)),
                 style={"opacity":0.75,"marginTop":"2px"}),

        html.Button("Save", id="bat-save", className="custom-tab", style={"marginTop":"10px"}),
        dcc.Interval(id="bat-tick", interval=10_000, n_intervals=0),

        footer_license(),
    ])

def register_callbacks(app):

    @app.callback(
        Output("bat-kpi-soc","children"),
        Output("bat-kpi-power","children"),
        Input("bat-tick","n_intervals"),
        State("bat-soc-ent","value"),
        State("bat-v-ent","value"),
        State("bat-i-ent","value"),
        prevent_initial_call=False
    )
    def _tick(_n, soc_ent, v_ent, i_ent):
        soc = get_sensor_value(soc_ent) if soc_ent else None
        try:
            soc = float(soc)
        except Exception:
            soc = None

        v = get_sensor_value(v_ent) if v_ent else None
        i = get_sensor_value(i_ent) if i_ent else None
        try: v = float(v)
        except Exception: v = None
        try: i = float(i)
        except Exception: i = None

        soc_line = f"SoC: {soc:.1f} %" if soc is not None else "SoC: n/a"
        if v is not None and i is not None:
            p = (v * i) / 1000.0
            if p >= 0:
                p_line = f"Measured power: +{p:.2f} kW (charging)"
            else:
                p_line = f"Measured power: {p:.2f} kW (discharging)"
        else:
            p_line = "Measured power: n/a"

        return soc_line, p_line

    @app.callback(
        Output("bat-save","children"),
        Input("bat-save","n_clicks"),
        State("bat-enabled","value"),
        State("bat-mode","value"),
        State("bat-cap","value"),
        State("bat-max-ch","value"),
        State("bat-max-disch","value"),
        State("bat-soc-ent","value"),
        State("bat-v-ent","value"),
        State("bat-i-ent","value"),
        State("bat-t-ent","value"),
        State("bat-target","value"),
        State("bat-reserve","value"),
        State("bat-grid-charge","value"),
        prevent_initial_call=True
    )
    def _save(n, en, mode, cap, maxch, maxdis, soc_e, v_e, i_e, t_e, tgt, res, grid_allow):
        if not n:
            raise dash.exceptions.PreventUpdate
        bat_set(
            enabled=bool(en and "on" in en),
            mode=("auto" if (mode and "auto" in mode) else "manual"),
            capacity_kwh=_num(cap,11.0),
            max_charge_kw=_num(maxch,0.0),
            max_discharge_kw=_num(maxdis,0.0),
            soc_entity=(soc_e or ""),
            dc_voltage_entity=(v_e or ""),
            dc_current_entity=(i_e or ""),
            temperature_entity=(t_e or ""),
            target_soc=_num(tgt,90.0),
            reserve_soc=_num(res,20.0),
            allow_grid_charge=bool(grid_allow and "allow" in grid_allow),
        )
        return "Saved ✓"
