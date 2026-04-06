# ui_pages/battery.py
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.battery_store import get_var as bat_get, set_vars as bat_set
from services.ha_sensors import get_sensor_value, list_entities_by_domain


def _sensor_options() -> list[dict]:
    """Alle sensor.* Entitaeten als Dropdown-Options."""
    try:
        sensors = list_entities_by_domain("sensor")
    except Exception:
        sensors = []
    return [{"label": s, "value": s} for s in sensors]


def _row():
    return {"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap", "marginBottom": "14px"}


def layout():
    enabled = bool(bat_get("enabled", False))
    cap = bat_get("capacity_entity", "")
    soc = bat_get("soc_entity", "")
    pwr = bat_get("power_entity", "")
    vdc = bat_get("voltage_entity", "")
    idc = bat_get("current_entity", "")
    temp = bat_get("temperature_entity", "")

    sensor_opts = _sensor_options()

    return html.Div(
        id="battery-page",
        children=[
            html.H2("Battery settings", className="page-title"),
            html.Div([
                html.Label("General"),
                dcc.Checklist(
                    id="bat-enabled-entity",
                    options=[{"label": " Enabled", "value": "on"}],
                    value=(["on"] if enabled else []),
                    persistence=True,
                    persistence_type="memory",
                    style={"marginBottom": "8px"},
                ),
            ], style={"marginBottom": "16px"}),
            html.Div([
                html.Label("Capacity sensor (kWh)"),
                dcc.Dropdown(
                    id="bat-cap-entity",
                    options=sensor_opts,
                    value=(cap or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "360px"},
                ),
                html.Span(id="bat-cap-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("SOC sensor (%)"),
                dcc.Dropdown(
                    id="bat-soc-entity",
                    options=sensor_opts,
                    value=(soc or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-soc-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Power sensor (kW/W, +charge / -discharge)"),
                dcc.Dropdown(
                    id="bat-power-entity",
                    options=sensor_opts,
                    value=(pwr or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-power-sensor-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("DC voltage (V)"),
                dcc.Dropdown(
                    id="bat-vdc-entity",
                    options=sensor_opts,
                    value=(vdc or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "360px"},
                ),
                html.Span(id="bat-vdc-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("DC current (A)"),
                dcc.Dropdown(
                    id="bat-idc-entity",
                    options=sensor_opts,
                    value=(idc or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "360px"},
                ),
                html.Span(id="bat-idc-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Temperature (C)"),
                dcc.Dropdown(
                    id="bat-temp-entity",
                    options=sensor_opts,
                    value=(temp or None),
                    placeholder="Select sensor...",
                    style={"minWidth": "360px"},
                ),
                html.Span(id="bat-temp-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Power (kW, live)"),
                html.Span(id="bat-power-val", style={"marginLeft": "12px", "fontWeight": "bold"}),
            ], style=_row()),
            html.Button("Save", id="bat-save", className="custom-tab"),
            html.Span(id="bat-save-status", style={"marginLeft": "8px", "color": "green"}),
            dcc.Interval(id="bat-scan", interval=1500, n_intervals=0, max_intervals=1),
            dcc.Interval(id="bat-live", interval=5000, n_intervals=0),
        ],
    )


def register_callbacks(app):
    @app.callback(
        Output("bat-save-status", "children"),
        Input("bat-save", "n_clicks"),
        State("bat-cap-entity", "value"),
        State("bat-soc-entity", "value"),
        State("bat-power-entity", "value"),
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        State("bat-enabled-entity", "value"),
        prevent_initial_call=True,
    )
    def _save(n, cap, soc, pwr, vdc, idc, temp, enabled_val):
        if not n:
            raise dash.exceptions.PreventUpdate
        bat_set(
            capacity_entity=cap or "",
            soc_entity=soc or "",
            power_entity=pwr or "",
            voltage_entity=vdc or "",
            current_entity=idc or "",
            temperature_entity=temp or "",
            enabled=bool(enabled_val and "on" in enabled_val),
        )
        return "Saved."

    @app.callback(
        Output("bat-cap-entity", "options"),
        Output("bat-soc-entity", "options"),
        Output("bat-power-entity", "options"),
        Output("bat-vdc-entity", "options"),
        Output("bat-idc-entity", "options"),
        Output("bat-temp-entity", "options"),
        Input("bat-scan", "n_intervals"),
        prevent_initial_call=True,
    )
    def _refresh_opts(_n):
        opts = _sensor_options()
        return opts, opts, opts, opts, opts, opts

    @app.callback(
        Output("bat-cap-val", "children"),
        Output("bat-soc-val", "children"),
        Output("bat-power-sensor-val", "children"),
        Output("bat-vdc-val", "children"),
        Output("bat-idc-val", "children"),
        Output("bat-temp-val", "children"),
        Output("bat-power-val", "children"),
        Input("bat-live", "n_intervals"),
        State("bat-cap-entity", "value"),
        State("bat-soc-entity", "value"),
        State("bat-power-entity", "value"),
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        prevent_initial_call=False,
    )
    def _live(_tick, cap_ent, soc_ent, pwr_ent, vdc_ent, idc_ent, temp_ent):
        def val(eid, fmt, unit=""):
            try:
                value = get_sensor_value(eid) if eid else None
                return (fmt.format(float(value)) + unit) if value is not None else "-"
            except Exception:
                return "-"

        def cap_text(eid):
            try:
                value = get_sensor_value(eid) if eid else None
                if value is None:
                    return "-"
                value = float(value)
                if value > 999:
                    value /= 1000.0
                return f"{value:.3f} kWh"
            except Exception:
                return "-"

        def power_text(raw):
            if raw is None:
                return None, "-"
            try:
                value = float(raw)
                if abs(value) > 300:
                    value /= 1000.0
                return value, "{:+.3f} kW".format(value)
            except Exception:
                return None, "-"

        cap = cap_text(cap_ent)
        soc = val(soc_ent, "{:.1f}", " %")
        pwr_sensor_raw = None if not pwr_ent else get_sensor_value(pwr_ent)
        pwr_sensor_num, pwr_sensor = power_text(pwr_sensor_raw)
        vdc_v = None if not vdc_ent else get_sensor_value(vdc_ent)
        idc_a = None if not idc_ent else get_sensor_value(idc_ent)
        vdc = ("{:.2f} V".format(float(vdc_v))) if vdc_v is not None else "-"
        idc = ("{:.2f} A".format(float(idc_a))) if idc_a is not None else "-"
        t = val(temp_ent, "{:.1f}", " C")

        if pwr_sensor_num is not None:
            mode = "charging" if pwr_sensor_num >= 0 else "discharging"
            pwr = "{:+.3f} kW ({})".format(pwr_sensor_num, mode)
        elif (vdc_v is not None) and (idc_a is not None):
            p_kw = (float(vdc_v) * float(idc_a)) / 1000.0
            mode = "charging" if p_kw >= 0 else "discharging"
            pwr = "{:+.3f} kW ({})".format(p_kw, mode)
        else:
            pwr = "-"

        return cap, soc, pwr_sensor, vdc, idc, t, pwr
