# ui_pages/sensors.py
from dash import html, dcc
from dash.dependencies import Input, Output, State
import os, yaml, dash
from services.ha_sensors import list_all_sensors

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

FIELDS = [
    ("pv_production",   "PV production sensor"),
    ("load_consumption","Load consumption sensor"),
    ("grid_feed_in",    "Grid feed-in sensor"),
]

def _read_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def _write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)

def _merge(defaults, overrides):
    out = {}
    out.update(defaults or {})
    out.update(overrides or {})
    return out

def load_merged_mapping():
    d = _read_yaml(SENS_DEF)
    o = _read_yaml(SENS_OVR)
    d = d.get("mapping", {}) if isinstance(d, dict) else {}
    o = o.get("mapping", {}) if isinstance(o, dict) else {}
    return _merge(d, o)

def layout():
    mapping = load_merged_mapping()
    rows = []
    for key, lbl in FIELDS:
        rows.append(html.Div([
            html.Label(lbl),
            dcc.Dropdown(
                id=f"dd-{key}",
                options=[{"label": "(loading…)", "value": ""}],  # echte Optionen via Callback
                value=mapping.get(key, ""),
                placeholder="select sensor…",
                style={"width": "100%", "color": "blue"}
            ),
        ], style={"marginBottom": "12px"}))
    rows += [
        html.Button("Save", id="btn-save-sensors", style={"marginTop": "10px"}),
        html.Div(id="save-sensors-status", style={"marginTop": "8px", "color": "green"}),
        dcc.Interval(id="sensors-load", interval=60_000, n_intervals=0)  # 1 Minute in Millisekunden
    ]
    return html.Div([html.H2("Sensors")] + rows)

def register_callbacks(app):
    # Dropdown-Optionen laden + Initialwerte setzen
    @app.callback(
        [Output(f"dd-{k}", "options") for k, _ in FIELDS] +
        [Output(f"dd-{k}", "value")   for k, _ in FIELDS],
        Input("sensors-load", "n_intervals")
    )
    def _populate(_):
        sensors = list_all_sensors() or []
        opts = [{"label": s, "value": s} for s in sensors]
        mapping = load_merged_mapping()
        option_outputs = [opts for _ in FIELDS]
        value_outputs  = [mapping.get(k, "") for k, _ in FIELDS]
        return option_outputs + value_outputs

    # Speichern: sensors.local.yaml + Spiegeln in pv_mining_local_config.yaml->entities
    @app.callback(
        Output("save-sensors-status", "children"),
        Input("btn-save-sensors", "n_clicks"),
        [State(f"dd-{k}", "value") for k, _ in FIELDS],
        prevent_initial_call=True
    )
    def _save(n_clicks, *values):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        mapping = {k: (v or "") for (k, _), v in zip(FIELDS, values)}

        # overrides schreiben
        ovr = _read_yaml(SENS_OVR)
        ovr["mapping"] = mapping
        _write_yaml(SENS_OVR, ovr)

        # Backward-Compat: Dashboard-entities spiegeln
        cfg = _read_yaml(MAIN_CFG)
        ents = cfg.get("entities", {}) or {}
        ents.update({
            "sensor_pv_production":  mapping.get("pv_production", ""),
            "sensor_load_consumption": mapping.get("load_consumption", ""),
            "sensor_grid_feed_in":   mapping.get("grid_feed_in", ""),
        })
        cfg["entities"] = ents
        _write_yaml(MAIN_CFG, cfg)

        return "saved!"
