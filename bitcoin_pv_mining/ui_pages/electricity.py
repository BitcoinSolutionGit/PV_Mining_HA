import os
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
from services.ha_sensors import list_all_sensors, get_sensor_value
from services.utils import load_yaml, save_yaml

CONFIG_DIR = "/config/pv_mining_addon"
ELEC_DEF = os.path.join(CONFIG_DIR, "electricity.yaml")
ELEC_OVR = os.path.join(CONFIG_DIR, "electricity.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

# ---------- helpers: nested get/set ----------
def _get_path(data: dict, path: str):
    cur = data or {}
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur

def _ensure_path(data: dict, path: str) -> dict:
    cur = data
    for k in path.split("."):
        cur = cur.setdefault(k, {})
    return cur

def _elec_get_var(key, default=None):
    """electricity.variables[key] aus .local, dann .yaml"""
    v = _get_path(load_yaml(ELEC_OVR, {}) or {}, f"electricity.variables.{key}")
    if v is None:
        v = _get_path(load_yaml(ELEC_DEF, {}) or {}, f"electricity.variables.{key}")
    return default if v is None else v

def _elec_resolve_price_sensor():
    """electricity.mapping.current_electricity_price (local>def), sonst legacy entities.*"""
    # mapping unter electricity.*
    for path in (ELEC_OVR, ELEC_DEF):
        m = _get_path(load_yaml(path, {}) or {}, "electricity.mapping") or {}
        sid = (m.get("current_electricity_price") or "").strip() if isinstance(m, dict) else ""
        if sid:
            return sid
    # legacy
    ents = (load_yaml(MAIN_CFG, {}) or {}).get("entities", {}) or {}
    return (ents.get("sensor_current_electricity_price", "") or "").strip()

def _elec_current_price():
    """float | None: fixed -> fixed_price_value; dynamic -> Sensorwert"""
    mode = str(_elec_get_var("pricing_mode", "") or "").lower()
    sensor_id = _elec_resolve_price_sensor()
    if mode not in ("fixed", "dynamic"):
        mode = "dynamic" if sensor_id else "fixed"

    if mode == "fixed":
        return float(_elec_get_var("fixed_price_value", 0.0) or 0.0)

    # dynamic -> Sensor lesen
    sid = sensor_id
    val = get_sensor_value(sid) if sid else None
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _elec_currency_symbol():
    c = str(_elec_get_var("currency", "EUR") or "EUR").upper()
    return "€" if c == "EUR" else c  # simpel: EUR -> €, sonst Code

# ---------- resolver für Sensor-IDs (rückwärtskompatibel) ----------
def resolve_sensor_id(kind: str) -> str:
    """
    Priorität:
    1) electricity.local.yaml -> electricity.mapping[kind]
    2) electricity.yaml       -> electricity.mapping[kind]
    3) (Legacy) *.yaml        -> top-level mapping[kind]
    4) (Electricity-legacy)   -> electricity.price_sensor / electricity.current_electricity_price
    5) pv_mining_local_config.yaml -> entities[<fallback_key>]
    """
    # 1/2: nested electricity.mapping
    for path_file in (ELEC_OVR, ELEC_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "electricity.mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()

    # 3: top-level mapping (alte Struktur, z.B. wie sensors.yaml)
    for path_file in (ELEC_OVR, ELEC_DEF):
        m = _get_path(load_yaml(path_file, {}) or {}, "mapping")
        if isinstance(m, dict):
            v = m.get(kind)
            if isinstance(v, str) and v.strip():
                return v.strip()

    # 4: electricity-Block (Electricity-spezifische Legacy-Felder)
    if kind == "current_electricity_price":
        for key in ("electricity.price_sensor", "electricity.current_electricity_price"):
            for path_file in (ELEC_OVR, ELEC_DEF):
                v = _get_path(load_yaml(path_file, {}) or {}, key)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    # 5: Legacy-Fallback
    cfg = load_yaml(MAIN_CFG, {}) or {}
    ents = cfg.get("entities", {}) or {}
    fallback_keys = {
        "current_electricity_price": "sensor_current_electricity_price",
    }
    return (ents.get(fallback_keys.get(kind, ""), "") or "").strip()

def set_mapping(kind: str, sensor_id: str):
    """Schreibt nach electricity.local.yaml -> electricity.mapping[kind] + Legacy-Spiegelung."""
    ovr = load_yaml(ELEC_OVR, {}) or {}
    elec = ovr.setdefault("electricity", {})
    mapping = elec.setdefault("mapping", {})
    mapping[kind] = (sensor_id or "").strip()
    save_yaml(ELEC_OVR, ovr)

    # Legacy-Spiegelung (nur für current_electricity_price nötig)
    if kind == "current_electricity_price":
        cfg = load_yaml(MAIN_CFG, {}) or {}
        cfg.setdefault("entities", {})
        cfg["entities"]["sensor_current_electricity_price"] = (sensor_id or "").strip()
        save_yaml(MAIN_CFG, cfg)

# ---------- variables read/write ----------
def _get_var(key: str, default=None):
    # local überschreibt base
    val = _get_path(load_yaml(ELEC_OVR, {}) or {}, f"electricity.variables.{key}")
    if val is None:
        val = _get_path(load_yaml(ELEC_DEF, {}) or {}, f"electricity.variables.{key}")
    return default if val is None else val

def _set_vars(**pairs):
    ovr = load_yaml(ELEC_OVR, {}) or {}
    vars_block = _ensure_path(ovr, "electricity.variables")
    for k, v in pairs.items():
        if v is not None:
            vars_block[k] = v
    save_yaml(ELEC_OVR, ovr)

# ---------- layout ----------
def layout():
    # Startwerte
    sensor_options = [{"label": s, "value": s} for s in list_all_sensors()]
    sensor_val = resolve_sensor_id("current_electricity_price")

    # pricing_mode: "fixed" | "dynamic"
    pricing_mode = (_get_var("pricing_mode", None) or "").lower()
    if pricing_mode not in ("fixed", "dynamic"):
        # Default: wenn Sensor zugeordnet -> dynamic, sonst fixed
        pricing_mode = "dynamic" if sensor_val else "fixed"

    fixed_active = (pricing_mode == "fixed")
    dyn_active = (pricing_mode == "dynamic")

    fixed_price_value = float(_get_var("fixed_price_value", 0.0) or 0.0)
    fee_down = float(_get_var("network_fee_down_value", 0.0) or 0.0)  # Bezug
    fee_up   = float(_get_var("network_fee_up_value", 0.0) or 0.0)    # Einspeisung

    return html.Div([
        html.H2("Configure your electricity values"),

        html.Div([
            html.Label("Pricing mode"),
            html.Div([
                dcc.Checklist(
                    id="elec-fixed-active",
                    options=[{"label": " Fixed price", "value": "on"}],
                    value=(["on"] if fixed_active else [])
                ),
                dcc.Checklist(
                    id="elec-dyn-active",
                    options=[{"label": " Dynamic (sensor)", "value": "on"}],
                    value=(["on"] if dyn_active else [])
                ),
            ], style={"display": "flex", "gap": "18px", "alignItems": "center"})
        ], style={"marginBottom": "12px"}),

        # Dynamic sensor row
        html.Div([
            html.Label("Dynamic price sensor"),
            dcc.Dropdown(
                id="sensor-current-electricity-price",
                options=sensor_options,
                value=sensor_val,
                placeholder="Select sensor..."
            ),
        ], id="elec-row-sensor", style={"marginTop": "6px", "display": ("block" if dyn_active else "none")}),

        # Fixed price row
        html.Div([
            html.Label("Fixed price value (per kWh)"),
            dcc.Input(
                id="elec-fixed-value",
                type="number",
                step="0.0001",
                min=0, max=2,
                value=fixed_price_value,
                style={"width": "180px"}
            ),
        ], id="elec-row-fixed", style={"marginTop": "6px", "display": ("block" if fixed_active else "none")}),

        html.Hr(),

        # Netzgebühren immer aktiv
        html.Div([
            html.Label("Network fee (down / import)"),
            dcc.Input(
                id="elec-fee-down",
                type="number",
                step="0.0001",
                min=0, max=2,
                value=fee_down,
                style={"width": "160px"}
            ),
            html.Span("  "),
            html.Label("Network fee (up / export)", style={"marginLeft": "16px"}),
            dcc.Input(
                id="elec-fee-up",
                type="number",
                step="0.0001",
                min=0, max=2,
                value=fee_up,
                style={"width": "160px"}
            ),
        ], style={"marginTop": "6px"}),

        html.Button("Save", id="save-electricity", style={"marginTop": "20px"}, className="custom-tab"),
        html.Div(id="save-electricity-status", style={"marginTop": "10px", "color": "green"})
    ])


# ---------- callbacks ----------
def register_callbacks(app):
    # Mutual exclusivity & Sichtbarkeit/Enable der Eingaben
    @app.callback(
        Output("elec-fixed-active", "value"),
        Output("elec-dyn-active", "value"),
        Output("sensor-current-electricity-price", "disabled"),
        Output("elec-fixed-value", "disabled"),
        Output("elec-row-sensor", "style"),
        Output("elec-row-fixed", "style"),
        Input("elec-fixed-active", "value"),
        Input("elec-dyn-active", "value"),
        prevent_initial_call=True
    )
    def toggle_mode(fixed_val, dyn_val):
        fixed_on = bool(fixed_val and "on" in fixed_val)
        dyn_on   = bool(dyn_val and "on" in dyn_val)

        # mind. eins muss aktiv sein, und nur eins darf aktiv sein
        ctx = dash.callback_context
        if fixed_on and dyn_on:
            # wer hat ausgelöst?
            triggered = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
            if triggered == "elec-fixed-active":
                dyn_on = False
            else:
                fixed_on = False
        elif not fixed_on and not dyn_on:
            # fallback: fixed aktivieren
            fixed_on = True

        # Sichtbarkeit & Disable
        sensor_disabled = not dyn_on
        fixed_disabled  = not fixed_on
        style_sensor = {"marginTop": "6px", "display": "block" if dyn_on else "none"}
        style_fixed  = {"marginTop": "6px", "display": "block" if fixed_on else "none"}

        return (
            (["on"] if fixed_on else []),
            (["on"] if dyn_on else []),
            sensor_disabled,
            fixed_disabled,
            style_sensor,
            style_fixed,
        )

    # Speichern
    @app.callback(
        Output("save-electricity-status", "children"),
        Input("save-electricity", "n_clicks"),
        State("elec-fixed-active", "value"),
        State("elec-dyn-active", "value"),
        State("sensor-current-electricity-price", "value"),
        State("elec-fixed-value", "value"),
        State("elec-fee-down", "value"),
        State("elec-fee-up", "value"),
        prevent_initial_call=True
    )
    def save_all(n_clicks, fixed_val, dyn_val, sensor_id, fixed_price, fee_down, fee_up):
        if not n_clicks:
            return ""

        fixed_on = bool(fixed_val and "on" in fixed_val)
        dyn_on   = bool(dyn_val and "on" in dyn_val)
        # Safety: nur eines aktiv, mindestens eines aktiv
        if fixed_on and dyn_on:
            # bevorzugt die zuletzt gewählte; hier einfach: dynamic gewinnt
            fixed_on, dyn_on = False, True
        if not fixed_on and not dyn_on:
            fixed_on = True

        pricing_mode = "fixed" if fixed_on else "dynamic"

        # Mapping immer schreiben (unschädlich, auch wenn fixed aktiv ist)
        set_mapping("current_electricity_price", sensor_id or "")

        # Variablen speichern
        _set_vars(
            pricing_mode=pricing_mode,
            fixed_price_value=float(fixed_price or 0.0),
            network_fee_down_value=float(fee_down or 0.0),
            network_fee_up_value=float(fee_up or 0.0),
        )

        return "Electricity settings saved!"