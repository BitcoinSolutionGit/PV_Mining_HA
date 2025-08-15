# ui_pages/wallbox.py
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.wallbox_store import get_var as wb_get, set_vars as wb_set
from services.ha_sensors import get_sensor_value
from services.ha_entities import list_actions
from services.electricity_store import currency_symbol

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def layout():
    actions = list_actions()
    sym = currency_symbol()
    data = {k: wb_get(k) for k in [
        "enabled","mode","max_charge_kw","phases","max_current_a",
        "connected_entity","power_entity","energy_session_entity","ready_entity",
        "action_on_entity","action_off_entity",
        "target_energy_kwh","solar_only","min_surplus_kw"
    ]}

    return html.Div([
        html.H2("Wallbox"),

        html.Div([
            html.Div([
                html.Label("Enabled"),
                dcc.Checklist(id="wb-enabled", options=[{"label":" on","value":"on"}],
                              value=(["on"] if data["enabled"] else []))
            ]),
            html.Div(style={"width":"14px"}),
            html.Div([
                html.Label("Mode (auto)"),
                dcc.Checklist(id="wb-mode", options=[{"label":" on","value":"auto"}],
                              value=(["auto"] if data["mode"]=="auto" else []))
            ]),
        ], style={"display":"flex","alignItems":"center","gap":"8px"}),

        html.Hr(),

        html.Div([
            html.Div([
                html.Label("Max charge power (kW)"),
                dcc.Input(id="wb-maxkw", type="number", step=0.5, value=_num(data["max_charge_kw"], 11.0), style={"width":"160px"})
            ]),
            html.Div([
                html.Label("Phases"),
                dcc.Dropdown(id="wb-phases", options=[{"label":"1","value":1},{"label":"3","value":3}],
                             value=int(data["phases"] or 3), style={"width":"120px"})
            ], style={"marginLeft":"10px"}),
            html.Div([
                html.Label("Max current (A)"),
                dcc.Input(id="wb-maxa", type="number", step=1, value=_num(data["max_current_a"], 16), style={"width":"140px"})
            ], style={"marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px"}),

        html.Div([
            html.Div([
                html.Label("Vehicle connected (bool entity)"),
                dcc.Input(id="wb-connected", type="text", value=data["connected_entity"], placeholder="binary_sensor.ev_connected", style={"minWidth":"280px"})
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Charge power (kW) entity"),
                dcc.Input(id="wb-power", type="text", value=data["power_entity"], placeholder="sensor.wallbox_power", style={"minWidth":"260px"})
            ], style={"flex":"1","marginLeft":"10px"}),
            html.Div([
                html.Label("Session energy (kWh) entity"),
                dcc.Input(id="wb-energy", type="text", value=data["energy_session_entity"], placeholder="sensor.wallbox_session_energy", style={"minWidth":"300px"})
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px","marginTop":"8px"}),

        html.Div([
            html.Div([
                html.Label("Ready/State entity (True = running)"),
                dcc.Input(id="wb-ready", type="text", value=data["ready_entity"], placeholder="binary_sensor.wallbox_charging", style={"minWidth":"300px"})
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Action START (script/switch)"),
                dcc.Dropdown(id="wb-act-on", options=actions, value=(data["action_on_entity"] or None), placeholder="Select script or switch…")
            ], style={"flex":"1","marginLeft":"10px"}),
            html.Div([
                html.Label("Action STOP (script/switch)"),
                dcc.Dropdown(id="wb-act-off", options=actions, value=(data["action_off_entity"] or None), placeholder="Select script or switch…")
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px","marginTop":"8px"}),

        html.Div([
            html.Div([
                html.Label("Target energy this session (kWh)"),
                dcc.Input(id="wb-target-kwh", type="number", step=0.5, value=_num(data["target_energy_kwh"], 10.0), style={"width":"200px"})
            ]),
            html.Div([
                html.Label("Solar-only"),
                dcc.Checklist(id="wb-solar-only", options=[{"label":" only charge on PV surplus","value":"on"}],
                              value=(["on"] if data["solar_only"] else []))
            ], style={"marginLeft":"10px"}),
            html.Div([
                html.Label("Min PV surplus to start (kW)"),
                dcc.Input(id="wb-min-surplus", type="number", step=0.1, value=_num(data["min_surplus_kw"], 1.0), style={"width":"180px"})
            ], style={"marginLeft":"10px"}),
        ], style={"display":"flex","alignItems":"center","gap":"10px","marginTop":"8px"}),

        html.Hr(),
        html.Div(id="wb-kpi", style={"fontWeight":"bold"}),
        html.Div(id="wb-kpi-sub", style={"opacity":0.8,"marginTop":"4px"}),

        html.Button("Save", id="wb-save", className="custom-tab", style={"marginTop":"10px"}),
        html.Span(id="wb-save-status", style={"marginLeft":"10px","color":"green"}),

        dcc.Interval(id="wb-refresh", interval=10_000, n_intervals=0)
    ])

def register_callbacks(app):
    @app.callback(
        Output("wb-save-status","children"),
        Input("wb-save","n_clicks"),
        State("wb-enabled","value"),
        State("wb-mode","value"),
        State("wb-maxkw","value"),
        State("wb-phases","value"),
        State("wb-maxa","value"),
        State("wb-connected","value"),
        State("wb-power","value"),
        State("wb-energy","value"),
        State("wb-ready","value"),
        State("wb-act-on","value"),
        State("wb-act-off","value"),
        State("wb-target-kwh","value"),
        State("wb-solar-only","value"),
        State("wb-min-surplus","value"),
        prevent_initial_call=True
    )
    def _save(n, en, mode, maxkw, ph, maxa, conn_e, pwr_e, ene_e, ready_e, aon, aoff, tgt_kwh, solar_only, min_surp):
        if not n:
            raise dash.exceptions.PreventUpdate
        wb_set(
            enabled=bool(en and "on" in en),
            mode=("auto" if (mode and "auto" in mode) else "manual"),
            max_charge_kw=_num(maxkw, 11.0),
            phases=int(ph or 3),
            max_current_a=int(_num(maxa, 16)),
            connected_entity=(conn_e or "").strip(),
            power_entity=(pwr_e or "").strip(),
            energy_session_entity=(ene_e or "").strip(),
            ready_entity=(ready_e or "").strip(),
            action_on_entity=(aon or ""),
            action_off_entity=(aoff or ""),
            target_energy_kwh=_num(tgt_kwh, 10.0),
            solar_only=bool(solar_only and "on" in solar_only),
            min_surplus_kw=_num(min_surp, 1.0),
        )
        return "Saved!"

    @app.callback(
        Output("wb-kpi","children"),
        Output("wb-kpi-sub","children"),
        Input("wb-refresh","n_intervals")
    )
    def _kpi(_n):
        maxkw = _num(wb_get("max_charge_kw", 11.0), 11.0)
        tgt = _num(wb_get("target_energy_kwh", 10.0), 10.0)

        conn_e = wb_get("connected_entity", "")
        pwr_e = wb_get("power_entity", "")
        ene_e = wb_get("energy_session_entity", "")
        ready_e = wb_get("ready_entity", "")

        connected = None
        if conn_e:
            v = get_sensor_value(conn_e)
            connected = str(v).lower() in ("on","true","1","yes")

        pwr = _num(get_sensor_value(pwr_e), None) if pwr_e else None
        ene = _num(get_sensor_value(ene_e), None) if ene_e else None

        ready = None
        if ready_e:
            v = get_sensor_value(ready_e)
            ready = str(v).lower() in ("on","true","1","yes")

        # Zeit bis Ziel-Energie (wenn Session-Energie vorhanden)
        remain = None
        if tgt is not None and ene is not None:
            remain = max(0.0, tgt - ene)

        time_txt = "–"
        if remain is not None:
            base_pw = (pwr if pwr is not None and pwr > 0 else maxkw)
            if base_pw > 0:
                time_txt = f"{(remain / base_pw):.1f} h to reach {tgt:.1f} kWh"

        main = f"Connected: {('✅' if connected else 'n/a' if connected is None else '❌')} · {time_txt}"
        sub = f"Charge power: {(f'{pwr:.2f} kW' if pwr is not None else f'up to {maxkw:.1f} kW')}"
        if ene is not None:
            sub += f" · Session: {ene:.1f} kWh"
        if ready is not None:
            sub += " · Ready: " + ("✅" if ready else "⏳/❌")

        return main, sub
