import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.ha_sensors import list_all_input_numbers, get_sensor_value
from services.heater_store import resolve_entity_id, set_mapping, get_var as heat_get_var, set_vars as heat_set_vars

def _num(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def _fmt_temp(v: float | None, unit: str) -> str:                            # NEW: Formatter
    if v is None:
        return "–"
    if unit == "K":
        v = v + 273.15
    return f"{v:.2f} {unit}"

# ---------- layout ----------
def layout():
    input_numbers = [{"label": e, "value": e} for e in list_all_input_numbers()]

    warmwasser_entity = resolve_entity_id("input_warmwasser_cache") or None
    heizstab_entity   = resolve_entity_id("input_heizstab_cache") or None

    wanted_temp = _num(heat_get_var("wanted_water_temperature", 60), 60)
    max_power   = _num(heat_get_var("max_power_heater", 0.0), 0.0)
    power_unit  = (heat_get_var("power_unit", "kW") or "kW")
    heat_unit   = (heat_get_var("heat_unit", "°C") or "°C")

    return html.Div([
        html.H2("Water Heater settings"),

        html.H4("Entity mapping (input_number)"),
        html.Div([
            html.Label("Warmwasser-Cache (Temperatur, °C)"),
            dcc.Dropdown(
                id="heater-input-warmwasser",
                options=input_numbers,
                value=warmwasser_entity,
                placeholder="input_number.warmwasser_cache",
            ),
        ], style={"marginBottom": "10px"}),

        html.Div([
            html.Label("Heizstab-Cache (Leistung, 0–100 %)"),
            dcc.Dropdown(
                id="heater-input-heizstab",
                options=input_numbers,
                value=heizstab_entity,
                placeholder="input_number.heizstab_cache",
            ),
        ], style={"marginBottom": "20px"}),

        html.H4("Variables"),
        html.Div([
            html.Label("Target water temperature"),
            dcc.Input(
                id="heater-wanted-temp",
                type="number", step="0.1", min=0, max=95,
                value=wanted_temp, style={"width": "140px"}
            ),
            html.Span(" "),
            dcc.Dropdown(
                id="heater-heat-unit",
                options=[{"label": "°C", "value": "°C"}, {"label": "K", "value": "K"}],
                value=heat_unit, clearable=False,
                style={"width": "100px", "display": "inline-block", "marginLeft": "8px"}
            ),
        ], style={"marginBottom": "10px"}),

        html.Div([
            html.Label("Max heater power"),
            dcc.Input(
                id="heater-max-power",
                type="number", step="0.1", min=0, max=50,
                value=max_power, style={"width": "140px"}
            ),
            html.Span(" "),
            dcc.Dropdown(
                id="heater-power-unit",
                options=[{"label": "kW", "value": "kW"}, {"label": "W", "value": "W"}],
                value=power_unit, clearable=False,
                style={"width": "100px", "display": "inline-block", "marginLeft": "8px"}
            ),
        ], style={"marginBottom": "16px"}),

        html.Button("Save", id="heater-save", className="custom-tab"),
        html.Div(id="heater-save-status", style={"marginTop": "10px", "color": "green"}),

        html.Hr(),

        # NEW: Live-Temperaturanzeige
        dcc.Interval(id="heater-refresh", interval=10_000, n_intervals=0),
        html.Div([
            html.Label("Aktuelle Wassertemperatur"),
            html.Div(id="heater-current-temp",
                     style={"fontWeight": "bold", "marginTop": "6px"})
        ], style={"marginTop": "10px"})
    ])

# ---------- callbacks ----------
def register_callbacks(app):
    @app.callback(
        Output("heater-save-status", "children"),
        Input("heater-save", "n_clicks"),
        State("heater-input-warmwasser", "value"),
        State("heater-input-heizstab", "value"),
        State("heater-wanted-temp", "value"),
        State("heater-heat-unit", "value"),
        State("heater-max-power", "value"),
        State("heater-power-unit", "value"),
        prevent_initial_call=True
    )
    def save_heater(n, warmwasser_id, heizstab_id, wanted_temp, heat_unit, max_power, power_unit):
        if not n:
            return ""
        # Mapping speichern
        set_mapping("input_warmwasser_cache", warmwasser_id or "")
        set_mapping("input_heizstab_cache",  heizstab_id or "")
        # Variablen speichern
        heat_set_vars(
            wanted_water_temperature=_num(wanted_temp, 60.0),
            max_power_heater=_num(max_power, 0.0),
            power_unit=(power_unit or "kW"),
            heat_unit=(heat_unit or "°C"),
        )
        return "Heater settings saved!"

    # NEW: Poll alle 10s + sofort bei Auswahl/Einheitenwechsel
    @app.callback(
        Output("heater-current-temp", "children"),
        Input("heater-refresh", "n_intervals"),
        Input("heater-input-warmwasser", "value"),
        Input("heater-heat-unit", "value"),
        prevent_initial_call=False
    )
    def update_current_temp(_tick, warmwasser_entity, unit):
        if not warmwasser_entity:
            return "–"
        try:
            raw = get_sensor_value(warmwasser_entity)
            val_c = _num(raw, None)           # Wert in °C erwartet (aus input_number)
            return _fmt_temp(val_c, unit or "°C")
        except Exception as e:
            return f"–"