# ui_pages/heater.py
import os
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State

from services.ha_sensors import list_all_sensors
from services.heater_store import (
    resolve_sensor_id, set_mapping,
    get_var as heat_get_var, set_vars as heat_set_vars
)

CONFIG_DIR = "/config/pv_mining_addon"
HEAT_DEF = os.path.join(CONFIG_DIR, "heater.yaml")
HEAT_OVR = os.path.join(CONFIG_DIR, "heater.local.yaml")

def _num(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

# ---------- layout ----------
def layout():
    # Entity-Auswahl
    all_entities = [{"label": s, "value": s} for s in list_all_sensors()]  # nutzt deine bestehende Discovery
    water_temp_entity = resolve_sensor_id("sensor_water_temperature") or None
    heater_percent_entity = resolve_sensor_id("slider_water_heater_percent") or None

    # Variablen
    wanted_temp = _num(heat_get_var("wanted_water_temperature", 60), 60)
    max_power = _num(heat_get_var("max_power_heater", 0.0), 0.0)
    power_unit = (heat_get_var("power_unit", "kW") or "kW")
    heat_unit = (heat_get_var("heat_unit", "°C") or "°C")

    # Caches (anzeige/optional editierbar -> disabled=True)
    cache_temp = _num(heat_get_var("cache_water_temperature", None))
    cache_pct  = _num(heat_get_var("cache_water_heater_percent", None))

    return html.Div([
        html.H2("Water Heater settings"),

        html.H4("Entity mapping"),
        html.Div([
            html.Label("Water temperature sensor"),
            dcc.Dropdown(
                id="heater-sensor-water-temp",
                options=all_entities,
                value=water_temp_entity,
                placeholder="Select temperature sensor…",
            ),
        ], style={"marginBottom": "10px"}),

        html.Div([
            html.Label("Heater percent slider (input_number)"),
            dcc.Dropdown(
                id="heater-entity-percent-slider",
                options=all_entities,
                value=heater_percent_entity,
                placeholder="Select percent slider…",
            ),
        ], style={"marginBottom": "20px"}),

        html.H4("Variables"),
        html.Div([
            html.Label("Target water temperature"),
            dcc.Input(
                id="heater-wanted-temp",
                type="number",
                step="0.1", min=0, max=95,
                value=wanted_temp,
                style={"width": "140px"}
            ),
            html.Span(" "),
            dcc.Dropdown(
                id="heater-heat-unit",
                options=[{"label": "°C", "value": "°C"}, {"label": "K", "value": "K"}],
                value=heat_unit,
                clearable=False,
                style={"width": "100px", "display": "inline-block", "marginLeft": "8px"}
            ),
        ], style={"marginBottom": "10px"}),

        html.Div([
            html.Label("Max heater power"),
            dcc.Input(
                id="heater-max-power",
                type="number",
                step="0.1", min=0, max=50,
                value=max_power,
                style={"width": "140px"}
            ),
            html.Span(" "),
            dcc.Dropdown(
                id="heater-power-unit",
                options=[{"label": "kW", "value": "kW"}, {"label": "W", "value": "W"}],
                value=power_unit,
                clearable=False,
                style={"width": "100px", "display": "inline-block", "marginLeft": "8px"}
            ),
        ], style={"marginBottom": "16px"}),

        html.Details([
            html.Summary("Cache (readonly)"),
            html.Div([
                html.Label("cache_water_temperature"),
                dcc.Input(id="heater-cache-temp", type="number", step="0.1",
                          value=cache_temp, disabled=True, style={"width": "140px"}),
                html.Span("  "),
                html.Label("cache_water_heater_percent", style={"marginLeft": "16px"}),
                dcc.Input(id="heater-cache-pct", type="number", step="1",
                          value=cache_pct, disabled=True, style={"width": "140px"}),
            ])
        ], open=False, style={"marginBottom": "20px"}),

        html.Button("Save", id="heater-save", className="custom-tab"),
        html.Div(id="heater-save-status", style={"marginTop": "10px", "color": "green"})
    ])

# ---------- callbacks ----------
def register_callbacks(app):
    # Nur speichern – keine komplexen Toggles nötig
    @app.callback(
        Output("heater-save-status", "children"),
        Input("heater-save", "n_clicks"),
        State("heater-sensor-water-temp", "value"),
        State("heater-entity-percent-slider", "value"),
        State("heater-wanted-temp", "value"),
        State("heater-heat-unit", "value"),
        State("heater-max-power", "value"),
        State("heater-power-unit", "value"),
        prevent_initial_call=True
    )
    def save_heater(n_clicks, sensor_temp, slider_pct, wanted_temp, heat_unit, max_power, power_unit):
        if not n_clicks:
            return ""

        # Mapping persistieren
        set_mapping("sensor_water_temperature", sensor_temp or "")
        set_mapping("slider_water_heater_percent", slider_pct or "")

        # Variablen persistieren
        heat_set_vars(
            wanted_water_temperature=_num(wanted_temp, 60.0),
            max_power_heater=_num(max_power, 0.0),
            power_unit=(power_unit or "kW"),
            heat_unit=(heat_unit or "°C"),
        )

        return "Heater settings saved!"
