# ui_pages/battery.py
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.battery_store import get_var as bat_get, set_vars as bat_set
from services.electricity_store import currency_symbol
from services.ha_sensors import get_sensor_value
from services.ha_entities import list_actions
from services.utils import load_yaml

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def _pct(x, d=0.0):
    v = _num(x, d)
    if v < 0: v = 0.0
    if v > 100: v = 100.0
    return v

def layout():
    sym = currency_symbol()
    data = {k: bat_get(k) for k in [
        "enabled","mode","capacity_kwh","max_charge_kw","max_discharge_kw",
        "soc_entity","power_entity","ready_entity",
        "action_on_entity","action_off_entity",
        "target_soc","reserve_soc","allow_grid_charge"
    ]}
    actions = list_actions()  # scripts & switches aus HA

    return html.Div([
        html.H2("Battery"),

        html.Div([
            html.Div([
                html.Label("Enabled"),
                dcc.Checklist(id="bat-enabled", options=[{"label":" on","value":"on"}],
                              value=(["on"] if data["enabled"] else []))
            ]),
            html.Div(style={"width":"14px"}),
            html.Div([
                html.Label("Mode (auto)"),
                dcc.Checklist(id="bat-mode", options=[{"label":" on","value":"auto"}],
                              value=(["auto"] if data["mode"]=="auto" else []))
            ]),
        ], style={"display":"flex","alignItems":"center","gap":"8px"}),

        html.Hr(),

        html.Div([
            html.Div([
                html.Label("Capacity (kWh)"),
                dcc.Input(id="bat-cap", type="number", step=0.1, value=_num(data["capacity_kwh"], 11.0), style={"width":"140px"})
            ]),
            html.Div([
                html.Label("Max charge power (kW)"),
                dcc.Input(id="bat-charge-kw", type="number", step=0.1, value=_num(data["max_charge_kw"], 3.0), style={"width":"140px"})
            ], style={"marginLeft":"10px"}),
            html.Div([
                html.Label("Max discharge power (kW)"),
                dcc.Input(id="bat-discharge-kw", type="number", step=0.1, value=_num(data["max_discharge_kw"], 3.0), style={"width":"160px"})
            ], style={"marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px"}),

        html.Div([
            html.Div([
                html.Label("SOC sensor entity (%, e.g. sensor.battery_soc)"),
                dcc.Input(id="bat-soc-entity", type="text", value=data["soc_entity"], placeholder="sensor.fronius_battery_soc", style={"minWidth":"340px"})
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Battery power entity (kW, optional)"),
                dcc.Input(id="bat-power-entity", type="text", value=data["power_entity"], placeholder="sensor.battery_power", style={"minWidth":"280px"})
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px","marginTop":"8px"}),

        html.Div([
            html.Div([
                html.Label("Ready/State entity (True = running)"),
                dcc.Input(id="bat-ready-entity", type="text", value=data["ready_entity"], placeholder="binary_sensor.battery_charging", style={"minWidth":"340px"})
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Action ON (script/switch)"),
                dcc.Dropdown(id="bat-act-on", options=actions, value=(data["action_on_entity"] or None), placeholder="Select script or switch…")
            ], style={"flex":"1","marginLeft":"10px"}),
            html.Div([
                html.Label("Action OFF (script/switch)"),
                dcc.Dropdown(id="bat-act-off", options=actions, value=(data["action_off_entity"] or None), placeholder="Select script or switch…")
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"10px","marginTop":"8px"}),

        html.Div([
            html.Div([
                html.Label("Target SOC (%)"),
                dcc.Input(id="bat-target-soc", type="number", step=1, value=_pct(data["target_soc"], 90.0), style={"width":"120px"})
            ]),
            html.Div([
                html.Label("Reserve SOC (%)"),
                dcc.Input(id="bat-reserve-soc", type="number", step=1, value=_pct(data["reserve_soc"], 20.0), style={"width":"120px"})
            ], style={"marginLeft":"10px"}),
            html.Div([
                html.Label("Allow grid charge (policy)"),
                dcc.Checklist(id="bat-grid-charge", options=[{"label":" allow","value":"on"}],
                              value=(["on"] if data["allow_grid_charge"] else []))
            ], style={"marginLeft":"10px"}),
        ], style={"display":"flex","alignItems":"center","gap":"10px","marginTop":"8px"}),

        html.Hr(),
        html.Div(id="bat-kpi", style={"fontWeight": "bold"}),
        html.Div(id="bat-kpi-sub", style={"opacity":0.8, "marginTop":"4px"}),

        html.Button("Save", id="bat-save", className="custom-tab", style={"marginTop":"10px"}),
        html.Span(id="bat-save-status", style={"marginLeft":"10px","color":"green"}),

        dcc.Interval(id="bat-refresh", interval=10_000, n_intervals=0)
    ])

def register_callbacks(app):
    @app.callback(
        Output("bat-save-status","children"),
        Input("bat-save","n_clicks"),
        State("bat-enabled","value"),
        State("bat-mode","value"),
        State("bat-cap","value"),
        State("bat-charge-kw","value"),
        State("bat-discharge-kw","value"),
        State("bat-soc-entity","value"),
        State("bat-power-entity","value"),
        State("bat-ready-entity","value"),
        State("bat-act-on","value"),
        State("bat-act-off","value"),
        State("bat-target-soc","value"),
        State("bat-reserve-soc","value"),
        State("bat-grid-charge","value"),
        prevent_initial_call=True
    )
    def _save(n, en, mode, cap, ckw, dkw, soc_e, pwr_e, ready_e, aon, aoff, tgt, rsv, grid_on):
        if not n:
            raise dash.exceptions.PreventUpdate
        bat_set(
            enabled=bool(en and "on" in en),
            mode=("auto" if (mode and "auto" in mode) else "manual"),
            capacity_kwh=_num(cap, 11.0),
            max_charge_kw=_num(ckw, 3.0),
            max_discharge_kw=_num(dkw, 3.0),
            soc_entity=(soc_e or "").strip(),
            power_entity=(pwr_e or "").strip(),
            ready_entity=(ready_e or "").strip(),
            action_on_entity=(aon or ""),
            action_off_entity=(aoff or ""),
            target_soc=_pct(tgt, 90.0),
            reserve_soc=_pct(rsv, 20.0),
            allow_grid_charge=bool(grid_on and "on" in grid_on),
        )
        return "Saved!"

    @app.callback(
        Output("bat-kpi","children"),
        Output("bat-kpi-sub","children"),
        Input("bat-refresh","n_intervals")
    )
    def _kpi(_n):
        cap = _num(bat_get("capacity_kwh", 11.0), 11.0)
        max_ckw = _num(bat_get("max_charge_kw", 3.0), 3.0)
        tgt = _pct(bat_get("target_soc", 90.0), 90.0)

        soc_e = bat_get("soc_entity", "")
        pwr_e = bat_get("power_entity", "")
        ready_e = bat_get("ready_entity", "")

        soc = _num(get_sensor_value(soc_e), None) if soc_e else None
        pwr = _num(get_sensor_value(pwr_e), None) if pwr_e else None
        ready = None
        if ready_e:
            v = get_sensor_value(ready_e)
            ready = str(v).lower() in ("on","true","1","yes")

        # Time to target (nur wenn SOC bekannt)
        time_txt = "–"
        if soc is not None and 0 <= soc <= 100 and max_ckw > 0:
            delta_kwh = max(0.0, cap * (tgt/100.0 - soc/100.0))
            hrs = (delta_kwh / max_ckw) if max_ckw > 0 else None
            if hrs is not None:
                time_txt = f"{hrs:.1f} h to reach {tgt:.0f}%"

        # Power-Anzeige
        if pwr is None:
            power_txt = f"Estimated charge power: up to {max_ckw:.1f} kW"
        else:
            power_txt = f"Charging power: {pwr:.2f} kW"

        # Ready-Flag
        ready_txt = "" if ready is None else (" · Ready: ✅" if ready else " · Ready: ⏳/❌")

        return (f"SoC: {('%.1f%%' % soc) if soc is not None else 'n/a'} · {time_txt}",
                power_txt + ready_txt)
