import os
import requests
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

# --- NEW: HA service helper (set input_number value) ---
def _ha_headers():
    tok = os.getenv("SUPERVISOR_TOKEN", "")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"} if tok else {"Content-Type": "application/json"}

def set_input_number_value(entity_id: str, value: float) -> bool:
    """Schreibt per Supervisor-Proxy auf input_number.set_value."""
    if not entity_id:
        return False
    try:
        r = requests.post(
            "http://supervisor/core/api/services/input_number/set_value",
            headers=_ha_headers(),
            json={"entity_id": entity_id, "value": float(value)},
            timeout=5
        )
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[heater] set_input_number_value failed: {e}", flush=True)
        return False

# ---------- layout ----------
def layout():
    input_numbers = [{"label": e, "value": e} for e in list_all_input_numbers()]

    warmwasser_entity = resolve_entity_id("input_warmwasser_cache") or None
    heizstab_entity   = resolve_entity_id("input_heizstab_cache") or None

    enabled     = bool(heat_get_var("enabled", False))
    wanted_temp = _num(heat_get_var("wanted_water_temperature", 60), 60)
    max_power   = _num(heat_get_var("max_power_heater", 0.0), 0.0)
    power_unit  = (heat_get_var("power_unit", "kW") or "kW")
    heat_unit   = (heat_get_var("heat_unit", "°C") or "°C")

    override_active = bool(heat_get_var("manual_override", False))
    override_percent = _num(heat_get_var("manual_override_percent", 0), 0)

    return html.Div([
        html.H2("Water Heater settings"),

        # Enabled-Schalter (neu)
        dcc.Checklist(
            id="heater-enabled",
            options=[{"label": " Enabled", "value": "on"}],
            value=(["on"] if enabled else []),
            style={"marginBottom": "12px"}
        ),
        html.Div(id="heater-enabled-status", style={"display":"none"}),

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
                type="number", step="0.001", min=0, max=95,
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
                type="number", step="0.001", min=0, max=50,
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

        # Temperaturanzeige
        dcc.Interval(id="heater-refresh", interval=10_000, n_intervals=0),
        html.Div([
            html.Label("Aktuelle Wassertemperatur"),
            html.Div(id="heater-current-temp",
                     style={"fontWeight": "bold", "marginTop": "6px"})
        ], style={"marginTop": "10px"}),

        html.Div(style={"height": "8px"}),

        # Live-Status unten ---
        dcc.Interval(id="heater-live-refresh", interval=10_000, n_intervals=0),  # 10s
        html.Div([
            html.Div([
                html.Label("Aktueller Heizstab (%)"),
                html.Div(id="heater-current-percent", style={"fontWeight": "bold", "marginTop": "4px"})
            ]),
            html.Div([
                html.Label("Aktuelle Leistung"),
                html.Div(id="heater-current-power", style={"fontWeight": "bold", "marginTop": "4px"})
            ], style={"marginLeft": "24px"}),
        ], style={"display": "flex", "alignItems": "baseline", "gap": "24px"}),

        html.Div(style={"height": "8px"}),

        # Mode (auto) + Slider ---
        html.Div([
            dcc.Checklist(
                id="heater-override",
                options=[{"label": " Mode (auto)", "value": "on"}],
                value=(["on"] if not override_active else []),  # checked = Auto
                style={"marginBottom": "8px"}
            ),
            dcc.Slider(
                id="heater-override-slider",
                min=0, max=100, step=1,
                value=override_percent,
                disabled=not override_active,  # Auto (manual_override=False) => disabled True
                marks=None, tooltip={"always_visible": False}
            ),
            html.Div(id="heater-override-status", style={"marginTop": "6px", "color": "green"})
        ], style={"maxWidth": "520px"})
    ])

# ---------- callbacks ----------
def register_callbacks(app):
    # Auto-persist Enabled toggle so Settings -> Prio-Liste reagiert sofort
    @app.callback(
        Output("heater-enabled-status","children"),
        Input("heater-enabled","value"),
        prevent_initial_call=True
    )
    def on_enabled_toggle(enabled_val):
        from services.heater_store import set_vars as heat_set_vars
        heat_set_vars(enabled=bool(enabled_val and "on" in enabled_val))
        return ""

    @app.callback(
        Output("heater-save-status", "children"),
        Input("heater-save", "n_clicks"),
        State("heater-enabled", "value"),
        State("heater-input-warmwasser", "value"),
        State("heater-input-heizstab", "value"),
        State("heater-wanted-temp", "value"),
        State("heater-heat-unit", "value"),
        State("heater-max-power", "value"),
        State("heater-power-unit", "value"),
        prevent_initial_call=True
    )
    def save_heater(n, enabled_val, warmwasser_id, heizstab_id, wanted_temp, heat_unit, max_power, power_unit):
        if not n:
            return ""
        # Mapping speichern
        set_mapping("input_warmwasser_cache", warmwasser_id or "")
        set_mapping("input_heizstab_cache",  heizstab_id or "")
        # Variablen speichern
        heat_set_vars(
            enabled=bool(enabled_val and "on" in enabled_val),
            wanted_water_temperature=_num(wanted_temp, 60.0),
            max_power_heater=_num(max_power, 0.0),
            power_unit=(power_unit or "kW"),
            heat_unit=(heat_unit or "°C"),
        )
        return "Heater settings saved!"

    # --- Slider enabled/disabled je nach Mode (Auto/Manuell) ---
    @app.callback(
        Output("heater-override-slider", "disabled"),
        Input("heater-override", "value"),
        State("heater-override-slider", "value"),
        State("heater-input-heizstab", "value"),
        prevent_initial_call=False
    )
    def toggle_slider(override_val, current_val, heizstab_entity):
        auto_on = bool(override_val and "on" in override_val)  # checked = Auto
        # Intern persistieren
        heat_set_vars(
            manual_override=(not auto_on),
            manual_override_percent=current_val or 0
        )
        # Optionaler "Kick": Beim Wechsel auf Auto einmalig auf 0% setzen
        if auto_on and heizstab_entity:
            try:
                set_input_number_value(heizstab_entity, 0)
            except Exception:
                pass
        # Auto => Slider disabled, Manuell => enabled
        return auto_on

    # --- Live-Update Prozent + Leistung + Slider-Sync (nur in Auto) ---
    @app.callback(
        Output("heater-current-percent", "children"),
        Output("heater-current-power", "children"),
        Output("heater-override-slider", "value"),
        Input("heater-live-refresh", "n_intervals"),
        Input("heater-input-heizstab", "value"),
        State("heater-max-power", "value"),
        State("heater-power-unit", "value"),
        State("heater-override", "value"),
        prevent_initial_call=False
    )
    def update_live(_tick, heizstab_entity, max_power, power_unit, override_val):
        import dash  # local import for dash.no_update
        pct_raw = get_sensor_value(heizstab_entity) if heizstab_entity else None
        pct = _num(pct_raw, 0.0)
        # Leistung ableiten
        pwr = (_num(max_power, 0.0) or 0.0) * (pct / 100.0)
        unit = power_unit or "kW"
        pct_text = f"{pct:.0f} %"
        pwr_text = f"{pwr:.2f} {unit}"

        # Slider nur synchronisieren, wenn Auto aktiv ist
        auto_on  = bool(override_val and "on" in override_val)
        slider_val = int(round(pct or 0)) if auto_on else dash.no_update

        return pct_text, pwr_text, slider_val

    # --- Bei Slider-Änderung -> nur im manuellen Modus in HA schreiben ---
    @app.callback(
        Output("heater-override-status", "children"),
        Input("heater-override-slider", "value"),
        State("heater-override", "value"),
        State("heater-input-heizstab", "value"),
        prevent_initial_call=True
    )
    def on_slider_change(new_value, override_val, heizstab_entity):
        # Immer persistieren
        heat_set_vars(manual_override_percent=new_value or 0)

        # In Auto nichts senden
        auto_on = bool(override_val and "on" in override_val)
        if auto_on:
            return ""

        if not heizstab_entity:
            return "no heater input selected."
        ok = set_input_number_value(heizstab_entity, new_value or 0)
        return "Override sent." if ok else "Error sending override."

    # --- Poll alle 10s + sofort bei Auswahl/Einheitenwechsel ---
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
        except Exception:
            return "–"
