import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.battery_store import get_override_state, get_var as bat_get, set_vars as bat_set
from services.ha_entities import get_entity_state, list_entity_options
from services.ha_sensors import get_sensor_value, list_entities_by_domain


def _sensor_options() -> list[dict]:
    try:
        sensors = list_entities_by_domain("sensor")
    except Exception:
        sensors = []
    return [{"label": s, "value": s} for s in sensors]


def _number_options() -> list[dict]:
    try:
        input_numbers = list_entities_by_domain("input_number")
    except Exception:
        input_numbers = []
    try:
        numbers = list_entities_by_domain("number")
    except Exception:
        numbers = []
    items = sorted(set(input_numbers + numbers))
    return [{"label": ent, "value": ent} for ent in items]


def _numeric_state_options() -> list[dict]:
    try:
        sensors = list_entities_by_domain("sensor")
    except Exception:
        sensors = []
    try:
        input_numbers = list_entities_by_domain("input_number")
    except Exception:
        input_numbers = []
    try:
        numbers = list_entities_by_domain("number")
    except Exception:
        numbers = []
    items = sorted(set(sensors + input_numbers + numbers))
    return [{"label": ent, "value": ent} for ent in items]


def _bool_action_options() -> list[dict]:
    return list_entity_options(("input_boolean", "switch", "script", "button"))


def _bool_state_options() -> list[dict]:
    return list_entity_options(("input_boolean", "switch"))


def _bool_feedback_options() -> list[dict]:
    return list_entity_options(("binary_sensor", "input_boolean", "switch"))


def _row():
    return {"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap", "marginBottom": "14px"}


def _fmt_live_state(entity_id: str, *, numeric: bool = False, unit: str = "") -> str:
    if not entity_id:
        return "-"
    raw = get_entity_state(entity_id)
    if raw is None:
        return "no data"
    if numeric:
        try:
            value = float(raw)
            return f"{value:.3f}{unit}"
        except Exception:
            return str(raw)
    return str(raw)


def _opt_num(value):
    return None if value in ("", None) else value


def layout():
    enabled = bool(bat_get("enabled", False))
    cap = bat_get("capacity_entity", "")
    soc = bat_get("soc_entity", "")
    vdc = bat_get("voltage_entity", "")
    idc = bat_get("current_entity", "")
    temp = bat_get("temperature_entity", "")

    neg_ctrl = bool(bat_get("neg_price_control_enabled", False))
    charge_allowed_entity = bat_get("charge_allowed_entity", "")
    charge_allowed_push_entity = bat_get("charge_allowed_push_entity", "")
    charge_allowed_feedback_entity = bat_get("charge_allowed_feedback_entity", "")
    target_soc_entity = bat_get("target_soc_entity", "")
    target_soc_push_entity = bat_get("target_soc_push_entity", "")
    target_soc_feedback_entity = bat_get("target_soc_feedback_entity", "")

    sensor_opts = _sensor_options()
    number_opts = _number_options()
    numeric_state_opts = _numeric_state_options()
    bool_state_opts = _bool_state_options()
    bool_action_opts = _bool_action_options()
    bool_feedback_opts = _bool_feedback_options()

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
            html.Hr(),
            html.H3("Negative price control"),
            html.Div(
                "Uses Home Assistant entities to force charge-friendly inverter settings while the effective grid price is negative. "
                "When the price becomes positive again or a fault occurs, the add-on actively restores normal values.",
                style={"opacity": 0.8, "marginBottom": "10px"},
            ),
            html.Div([
                dcc.Checklist(
                    id="bat-neg-ctrl-enabled",
                    options=[{"label": " Enable negative-price battery control", "value": "on"}],
                    value=(["on"] if neg_ctrl else []),
                    style={"marginBottom": "8px"},
                ),
            ], style={"marginBottom": "6px"}),
            html.Div([
                html.Label("Charge allowed entity (single switch/input_boolean)"),
                dcc.Dropdown(
                    id="bat-charge-allowed-entity",
                    options=bool_state_opts,
                    value=(charge_allowed_entity or None),
                    placeholder="Optional: switch.* or input_boolean.*",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-charge-allowed-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Charge allowed push action"),
                dcc.Dropdown(
                    id="bat-charge-allowed-push-entity",
                    options=bool_action_opts,
                    value=(charge_allowed_push_entity or None),
                    placeholder="Optional: script.* to push helper to inverter",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-charge-allowed-push-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Charge allowed feedback entity"),
                dcc.Dropdown(
                    id="bat-charge-allowed-feedback-entity",
                    options=bool_feedback_opts,
                    value=(charge_allowed_feedback_entity or None),
                    placeholder="Optional: binary_sensor.* / switch.* / input_boolean.*",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-charge-allowed-feedback-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Target SoC entity (%, optional)"),
                dcc.Dropdown(
                    id="bat-target-soc-entity",
                    options=number_opts,
                    value=(target_soc_entity or None),
                    placeholder="Optional: number.* or input_number.*",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-target-soc-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Target SoC push action"),
                dcc.Dropdown(
                    id="bat-target-soc-push-entity",
                    options=bool_action_opts,
                    value=(target_soc_push_entity or None),
                    placeholder="Optional: script.* to push helper to inverter",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-target-soc-push-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Target SoC feedback entity"),
                dcc.Dropdown(
                    id="bat-target-soc-feedback-entity",
                    options=numeric_state_opts,
                    value=(target_soc_feedback_entity or None),
                    placeholder="Optional: sensor.* / number.* / input_number.*",
                    style={"minWidth": "420px"},
                ),
                html.Span(id="bat-target-soc-feedback-val", style={"marginLeft": "12px", "opacity": 0.8}),
            ], style=_row()),
            html.Div([
                html.Label("Negative-price Target SoC (%)"),
                dcc.Input(id="bat-target-soc-negative", type="number", value=bat_get("target_soc_negative_pct", 100.0), style={"width": "140px"}),
                html.Label("Normal Target SoC (%, optional)", style={"marginLeft": "12px"}),
                dcc.Input(id="bat-target-soc-normal", type="number", value=bat_get("target_soc_normal_pct", None), style={"width": "140px"}),
            ], style=_row()),
            html.Div([
                html.Label("Control status"),
                html.Span(id="bat-neg-ctrl-status", style={"marginLeft": "12px", "fontWeight": "bold"}),
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
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        State("bat-enabled-entity", "value"),
        State("bat-neg-ctrl-enabled", "value"),
        State("bat-charge-allowed-entity", "value"),
        State("bat-charge-allowed-push-entity", "value"),
        State("bat-charge-allowed-feedback-entity", "value"),
        State("bat-target-soc-entity", "value"),
        State("bat-target-soc-push-entity", "value"),
        State("bat-target-soc-feedback-entity", "value"),
        State("bat-target-soc-negative", "value"),
        State("bat-target-soc-normal", "value"),
        prevent_initial_call=True,
    )
    def _save(
        n,
        cap,
        soc,
        vdc,
        idc,
        temp,
        enabled_val,
        neg_ctrl_val,
        charge_allowed_ent,
        charge_allowed_push_ent,
        charge_allowed_feedback_ent,
        target_soc_ent,
        target_soc_push_ent,
        target_soc_feedback_ent,
        target_soc_neg,
        target_soc_normal,
    ):
        if not n:
            raise dash.exceptions.PreventUpdate
        bat_set(
            capacity_entity=cap or "",
            soc_entity=soc or "",
            power_entity="",
            voltage_entity=vdc or "",
            current_entity=idc or "",
            temperature_entity=temp or "",
            enabled=bool(enabled_val and "on" in enabled_val),
            neg_price_control_enabled=bool(neg_ctrl_val and "on" in neg_ctrl_val),
            discharge_limit_entity="",
            discharge_limit_negative_w=0.0,
            discharge_limit_normal_w=None,
            charge_allowed_entity=charge_allowed_ent or "",
            charge_allowed_on_entity="",
            charge_allowed_off_entity="",
            charge_allowed_push_entity=charge_allowed_push_ent or "",
            charge_allowed_feedback_entity=charge_allowed_feedback_ent or "",
            charge_power_entity="",
            charge_power_negative_w=None,
            charge_power_normal_w=None,
            target_soc_entity=target_soc_ent or "",
            target_soc_push_entity=target_soc_push_ent or "",
            target_soc_feedback_entity=target_soc_feedback_ent or "",
            target_soc_negative_pct=float(target_soc_neg or 100.0),
            target_soc_normal_pct=_opt_num(target_soc_normal),
        )
        return "Saved."

    @app.callback(
        Output("bat-cap-entity", "options"),
        Output("bat-soc-entity", "options"),
        Output("bat-vdc-entity", "options"),
        Output("bat-idc-entity", "options"),
        Output("bat-temp-entity", "options"),
        Output("bat-target-soc-entity", "options"),
        Output("bat-charge-allowed-entity", "options"),
        Output("bat-charge-allowed-push-entity", "options"),
        Output("bat-charge-allowed-feedback-entity", "options"),
        Output("bat-target-soc-push-entity", "options"),
        Output("bat-target-soc-feedback-entity", "options"),
        Input("bat-scan", "n_intervals"),
        prevent_initial_call=True,
    )
    def _refresh_opts(_n):
        sensor_opts = _sensor_options()
        number_opts = _number_options()
        numeric_state_opts = _numeric_state_options()
        bool_state_opts = _bool_state_options()
        bool_action_opts = _bool_action_options()
        bool_feedback_opts = _bool_feedback_options()
        return (
            sensor_opts, sensor_opts, sensor_opts, sensor_opts, sensor_opts,
            number_opts,
            bool_state_opts,
            bool_action_opts, bool_feedback_opts,
            bool_action_opts, numeric_state_opts,
        )

    @app.callback(
        Output("bat-cap-val", "children"),
        Output("bat-soc-val", "children"),
        Output("bat-vdc-val", "children"),
        Output("bat-idc-val", "children"),
        Output("bat-temp-val", "children"),
        Output("bat-power-val", "children"),
        Output("bat-charge-allowed-val", "children"),
        Output("bat-charge-allowed-push-val", "children"),
        Output("bat-charge-allowed-feedback-val", "children"),
        Output("bat-target-soc-val", "children"),
        Output("bat-target-soc-push-val", "children"),
        Output("bat-target-soc-feedback-val", "children"),
        Output("bat-neg-ctrl-status", "children"),
        Input("bat-live", "n_intervals"),
        State("bat-cap-entity", "value"),
        State("bat-soc-entity", "value"),
        State("bat-vdc-entity", "value"),
        State("bat-idc-entity", "value"),
        State("bat-temp-entity", "value"),
        State("bat-charge-allowed-entity", "value"),
        State("bat-charge-allowed-push-entity", "value"),
        State("bat-charge-allowed-feedback-entity", "value"),
        State("bat-target-soc-entity", "value"),
        State("bat-target-soc-push-entity", "value"),
        State("bat-target-soc-feedback-entity", "value"),
        prevent_initial_call=False,
    )
    def _live(
        _tick,
        cap_ent,
        soc_ent,
        vdc_ent,
        idc_ent,
        temp_ent,
        charge_allowed_ent,
        charge_allowed_push_ent,
        charge_allowed_feedback_ent,
        target_soc_ent,
        target_soc_push_ent,
        target_soc_feedback_ent,
    ):
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
        vdc_v = None if not vdc_ent else get_sensor_value(vdc_ent)
        idc_a = None if not idc_ent else get_sensor_value(idc_ent)
        vdc = ("{:.2f} V".format(float(vdc_v))) if vdc_v is not None else "-"
        idc = ("{:.2f} A".format(float(idc_a))) if idc_a is not None else "-"
        t = val(temp_ent, "{:.1f}", " C")

        if (vdc_v is not None) and (idc_a is not None):
            p_kw = (float(vdc_v) * float(idc_a)) / 1000.0
            mode = "charging" if p_kw >= 0 else "discharging"
            pwr = "{:+.3f} kW ({})".format(p_kw, mode)
        else:
            pwr = "-"

        runtime = get_override_state()
        status = str(runtime.get("status") or "idle")
        error = str(runtime.get("error") or "").strip()
        ctrl_status = f"{status}: {error}" if error else status

        return (
            cap,
            soc,
            vdc,
            idc,
            t,
            pwr,
            _fmt_live_state(charge_allowed_ent),
            _fmt_live_state(charge_allowed_push_ent),
            _fmt_live_state(charge_allowed_feedback_ent),
            _fmt_live_state(target_soc_ent, numeric=True, unit=" %"),
            _fmt_live_state(target_soc_push_ent),
            _fmt_live_state(target_soc_feedback_ent, numeric=True, unit=" %"),
            ctrl_status,
        )
