# ui_pages/settings.py
import json
import dash
import os
from dash import html, dcc
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from services.settings_store import get_var as set_get, set_vars as set_set
from services.electricity_store import resolve_sensor_id as elec_resolve, set_mapping as elec_set_mapping, get_var as elec_get, set_vars as elec_set_vars
from services.ha_sensors import list_all_sensors, get_sensor_value
from services.forex import usd_to_eur_rate
from services.miners_store import list_miners
from services.cooling_store import get_cooling
from services.battery_store import get_var as bat_get
from services.wallbox_store import get_var as wb_get
from services.heater_store import resolve_entity_id as heat_resolve, get_var as heat_get
from ui_pages.common import footer_license, number_stepper
from services.utils import load_yaml, save_yaml

PRIO_KEY = "priority_order"
PRIO_KEY_JSON = "priority_order_json"
CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
ELEC_DEF = os.path.join(CONFIG_DIR, "electricity.yaml")
ELEC_OVR = os.path.join(CONFIG_DIR, "electricity.local.yaml")

PRIO_COLORS = {
    "inflow":    "#FFD700",
    "miners":    "#FF9900",
    "battery":   "#8E44AD",
    "heater":    "#3399FF",
    "wallbox":   "#33d1c6",
    "grid_feed": "#FF3333",
    "load":      "#A0A0A0",
    "inactive":  "#DDDDDD",
}

# Theme-aligned dark border
UI_BORDER = "rgba(191, 205, 229, 0.18)"

# ------------------------
# Helpers
# ------------------------

def _fieldset_style():
    return {
        "border": f"1px solid {UI_BORDER}",
        "borderRadius": "18px",
        "padding": "18px 18px 16px",
        "marginBottom": "14px",
        "background": "linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.03))",
        "boxShadow": "0 24px 60px rgba(5, 10, 20, 0.32)",
    }

def _input_style(width_px: int):
    return {
        "width": f"{width_px}px",
        "height": "40px",
        "lineHeight": "40px",
        "border": f"1px solid {UI_BORDER}",
        "borderRadius": "12px",
        "padding": "0 12px",
        "background": "rgba(10, 16, 28, 0.86)",
        "color": "#f4f7ff",
    }

def _sensor_value_style():
    return {
        "marginTop": "6px",
        "fontSize": "0.9rem",
        "opacity": 0.8,
    }

def _section(title: str, body_children):
    return html.Div([
        html.H3(title, className="settings-section-title"),
        html.Div(body_children, className="settings-card", style=_fieldset_style()),
    ], className="settings-section")

def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d

def _truthy(val, default=False):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on", "auto", "automatic", "enabled")

def _format_sensor_value(value):
    if value is None:
        return "no data"
    if isinstance(value, float):
        abs_val = abs(value)
        if abs_val >= 100.0:
            return f"{value:.1f}"
        if abs_val >= 10.0:
            return f"{value:.2f}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)

def _sensor_value_text(entity_id: str) -> str:
    entity_id = (entity_id or "").strip()
    if not entity_id:
        return "Current sensor value: no sensor selected"
    return f"Current sensor value: {_format_sensor_value(get_sensor_value(entity_id))}"

def _sensor_value_readout(readout_id: str, entity_id: str):
    return html.Div(
        _sensor_value_text(entity_id),
        id=readout_id,
        className="settings-subtle-text",
        style=_sensor_value_style(),
    )

def _is_battery_active() -> bool:
    return bool(bat_get("enabled", False))

def _is_battery_auto() -> bool:
    return str(bat_get("mode", "manual")).lower().startswith("auto")

def _is_wallbox_active() -> bool:
    return bool(wb_get("enabled", False))

def _is_wallbox_auto() -> bool:
    return str(wb_get("mode", "manual")).lower().startswith("auto")

def _is_heater_active() -> bool:
    try:
        en   = heat_get("enabled", None)
        heid = (heat_resolve("input_heizstab_cache") or "").strip()
        wwid = (heat_resolve("input_warmwasser_cache") or "").strip()
        maxp = _num(heat_get("max_power_heater", 0.0), 0.0)
        return bool((en is True) or (heid and wwid and maxp > 0.0))
    except Exception:
        return False


def _is_heater_auto() -> bool:
    # manual_override=True bedeutet: manuell; Auto ist also False
    try:
        return not bool(heat_get("manual_override", False))
    except Exception:
        return True

def _is_cooling_enabled() -> bool:
    # Cooling-Feature + cooling.enabled
    if not bool(set_get("cooling_feature_enabled", False)):
        return False
    c = get_cooling() or {}
    return bool(c.get("enabled", True))

def _is_miner_enabled(m: dict) -> bool:
    # versuche gängige Felder; default True
    for k in ("enabled", "is_enabled", "active"):
        if k in m:
            return _truthy(m.get(k), default=True)
    return True

def _resolve_sensor_id(kind: str) -> str:
    """
    kind ∈ {"pv_production","grid_consumption","grid_feed_in"}
    """
    mapping_def = load_yaml(SENS_DEF, {}).get("mapping", {})
    mapping_ovr = load_yaml(SENS_OVR, {}).get("mapping", {})
    sid = (mapping_ovr.get(kind) or mapping_def.get(kind) or "").strip()
    if sid:
        return sid
    cfg = load_yaml(MAIN_CFG, {})
    ents = cfg.get("entities", {})
    fallback_keys = {
        "pv_production": "sensor_pv_production",
        "grid_consumption": "sensor_grid_consumption",
        "grid_feed_in": "sensor_grid_feed_in",
    }
    return (ents.get(fallback_keys[kind], "") or "").strip()

def _is_cooling_auto_enabled() -> bool:
    """
    Cooling erscheint NUR wenn Feature aktiv UND Cooling auf Auto steht.
    Primärquelle: cooling_store.get_cooling()['mode'].
    """
    if not bool(set_get("cooling_feature_enabled", False)):
        return False

    c = get_cooling() or {}
    mode = (c.get("mode") or "").lower()
    if mode in ("auto", "automatic"):
        return True
    if mode in ("manual", "manuell", "override", "off", "disabled"):
        return False

    # Fallback: alte/alternative Settings-Flags, falls vorhanden
    s_mode = (set_get("cooling_control_mode", "") or set_get("cooling_mode", "") or "").lower()
    if s_mode in ("auto", "automatic"):
        return True
    if s_mode in ("manual", "manuell", "override", "off", "disabled"):
        return False

    auto_flag = set_get("cooling_auto", None)
    if auto_flag is None:
        auto_flag = set_get("cooling_auto_enabled", None)
    return _truthy(auto_flag, default=False)

def _is_miner_auto(m: dict) -> bool:
    """
    Miner nur anzeigen, wenn Auto-Modus.
    Versucht mehrere übliche Felder, fällt sonst auf Settings-Keys zurück:
    - miner.<id>.auto  | miner_<id>_auto | <id>_auto
    """
    # 1) Felder direkt am Miner-Objekt
    for key in ("auto", "automation", "auto_mode", "is_auto", "automatic"):
        if key in m:
            return _truthy(m.get(key), default=True)

    mode = (m.get("mode")
            or m.get("control_mode")
            or m.get("operation_mode")
            or m.get("state")
            or "").lower()
    if mode in ("manual", "manuell", "override"):
        return False
    if mode in ("auto", "automatic"):
        return True

    # 2) Fallback: Settings-Keys
    mid = m.get("id") or ""
    for k in (f"miner.{mid}.auto", f"miner_{mid}_auto", f"{mid}_auto"):
        v = set_get(k, None)
        if v is not None:
            return _truthy(v, default=True)

    # 3) Default: True (lieber zeigen, wenn unklar)
    return True

def _prio_available_items():
    """
    Welche Verbraucher sind aktuell durch den Planner steuerbar?
    Manual-Devices gehören nicht in die Priorisierungsliste.
    """
    items = []

    try:
        for m in list_miners() or []:
            if not _is_miner_enabled(m):
                continue
            if not _is_miner_auto(m):
                continue
            items.append({
                "id": f"miner:{m['id']}",
                "label": m.get("name", "Miner"),
                "color": PRIO_COLORS["miners"],
            })
    except Exception:
        pass

    if _is_battery_active():
        items.append({"id": "battery", "label": "Battery", "color": PRIO_COLORS["battery"]})
    if _is_wallbox_active() and _is_wallbox_auto():
        items.append({"id": "wallbox", "label": "Wallbox", "color": PRIO_COLORS["wallbox"]})
    if _is_heater_active() and _is_heater_auto():
        items.append({"id": "heater", "label": "Water Heater", "color": PRIO_COLORS["heater"]})

    # House & Grid Feed immer sichtbar
    items += [
        {"id": "house", "label": "House load", "color": PRIO_COLORS["load"]},
        {"id": "grid_feed", "label": "Grid feed-in", "color": PRIO_COLORS["grid_feed"]},
    ]

    # De-dupe
    seen, dedup = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"]); dedup.append(it)
    return dedup

def _prio_merge_with_stored(stored_ids, available):
    """Gespeicherte Reihenfolge mit Verfügbarem mergen, Neues hinten anhängen,
       grid_feed immer ganz unten."""
    avail_ids = [a["id"] for a in available]
    order = [x for x in (stored_ids or []) if x in avail_ids and x != "cooling"]
    for aid in avail_ids:
        if aid not in order and aid != "grid_feed":
            order.append(aid)
    if "grid_feed" in avail_ids:
        order = [x for x in order if x != "grid_feed"] + ["grid_feed"]
    return order

def _load_prio_ids():
    raw = set_get(PRIO_KEY, None)
    if isinstance(raw, list) and raw:
        return raw
    raw_json = set_get(PRIO_KEY_JSON, "")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            val = json.loads(raw_json)
            if isinstance(val, list) and val:
                return val
        except Exception:
            pass
    return []

def _save_prio_ids(ids):
    try:
        set_set(**{PRIO_KEY: ids})
    except Exception:
        pass
    try:
        set_set(**{PRIO_KEY_JSON: json.dumps(ids)})
    except Exception:
        pass
    print("[prio] saved:", ids, flush=True)

# ------------------------
# UI (↑/↓, Auto-Save)
# ------------------------

def _row_styles():
    return {
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "gap": "12px",
        "padding": "12px 14px",
        "marginBottom": "10px",
        "border": f"1px solid {UI_BORDER}",   # <— einheitlich
        "borderRadius": "18px",
        "background": "rgba(255, 255, 255, 0.05)",
        "fontSize": "16px",
        "fontWeight": "600",
    }

def _color_dot(color):
    return html.Span("", style={
        "display": "inline-block", "width": "12px", "height": "12px",
        "borderRadius": "50%", "backgroundColor": color
    })

def _prio_row(item, idx, order):
    # Bewegungsgrenzen berechnen
    last_idx = len(order) - 1
    last_movable = last_idx - 1 if (order and order[-1] == "grid_feed") else last_idx
    is_grid = (item["id"] == "grid_feed")

    disable_up = is_grid or idx == 0
    disable_down = is_grid or idx >= last_movable

    return html.Div(
        [
            html.Div([
                _color_dot(item.get("color", "#ccc")),
                html.Strong(item.get("label", "")),
            ], style={"display": "flex", "alignItems": "center"}),

            html.Div([
                html.Button("↑", id={"type": "prio-move-up", "index": idx},
                            n_clicks=0, disabled=disable_up,
                            style={"padding": "4px 10px", "borderRadius": "6px"}),
                html.Button("↓", id={"type": "prio-move-down", "index": idx},
                            n_clicks=0, disabled=disable_down,
                            style={"padding": "4px 10px", "borderRadius": "6px", "marginLeft": "6px"}),
            ], style={"marginLeft": "auto"})
        ],
        style=_row_styles()
    )


# --------------------------------
# Public API (used by main.py too)
# --------------------------------
# Lass die Namen exportiert, falls main.py darauf importiert.

def layout():
    # initiale Settings
    policy   = (set_get("pv_cost_policy", "zero") or "zero").lower()
    mode     = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fi_val   = _num(set_get("feedin_price_value", 0.0), 0.0)
    fi_sens  = set_get("feedin_price_sensor", "") or ""
    currency = (set_get("btc_price_currency", "EUR") or "EUR").upper()
    reward   = _num(set_get("block_reward_btc", 3.125), 3.125)
    tax_pct  = _num(set_get("sell_tax_percent", 0.0), 0.0)

    # NEW: Planner-Guard Defaults
    guard_w   = _num(set_get("surplus_guard_w", 100.0), 100.0)
    guard_pct = _num(set_get("surplus_guard_pct", 0.0), 0.0)  # als Anteil (0.00–0.05)

    # --- Miner Hysterese & Anti-Flattern ---
    miner_on_margin   = _num(set_get("miner_profit_on_eur_h",  0.05),  0.05)
    miner_off_margin  = _num(set_get("miner_profit_off_eur_h", -0.01), -0.01)
    miner_min_run_s   = int(_num(set_get("miner_min_run_s",  30), 30))
    miner_min_off_s   = int(_num(set_get("miner_min_off_s", 20), 20))

    sensors = [{"label": s, "value": s} for s in list_all_sensors()]
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    eff_pv_cost = max((fi_val if mode == "fixed" else _num(get_sensor_value(fi_sens), 0.0)) - fee_up, 0.0) if policy == "feedin" else 0.0
    cooling_enabled = bool(set_get("cooling_feature_enabled", False))

    # Defaults lesen
    export_cap = _num(set_get("grid_export_cap_kw", 0.0), 0.0)
    boost_cooldown = int(_num(set_get("boost_cooldown_s", 30), 30))
    allow_pv_ramp_up = bool(set_get("allow_pv_ramp_up", True))
    pv_ramp_settle_s = int(_num(set_get("pv_ramp_settle_s", 60), 60))
    pv_ramp_hysteresis_w = _num(set_get("pv_ramp_hysteresis_w", 200.0), 200.0)
    pv_ramp_step_up_kw = _num(set_get("pv_ramp_step_up_kw", 0.40), 0.40)
    pv_ramp_step_down_kw = _num(set_get("pv_ramp_step_down_kw", 0.60), 0.60)
    cool_on_frac = _num(set_get("cooling_on_fraction", 0.50), 0.50)
    miner_on_frac = _num(set_get("miner_on_fraction", _num(set_get("discrete_on_fraction", 0.95), 0.95)), 0.95)
    cool_min_run = int(_num(set_get("cooling_min_run_s", 20), 20))
    cool_min_off = int(_num(set_get("cooling_min_off_s", 20), 20))

    return html.Div([
        html.H2("Settings", className="page-title"),
        dcc.Interval(id="set-sensor-values-interval", interval=10000, n_intervals=0),

    # --- NEW: SENSORS (top) ---
    _section("Sensors", [
        html.Label("PV production"),
        dcc.Dropdown(
            id="set-sens-pv",
            options=[{"label": s, "value": s} for s in list_all_sensors()],
            value=_resolve_sensor_id("pv_production") or None,
            placeholder="Select sensor..."
        ),
        _sensor_value_readout("set-sens-pv-read", _resolve_sensor_id("pv_production")),
        html.Label("Grid consumption", style={"marginTop": "12px"}),
        dcc.Dropdown(
            id="set-sens-grid",
            options=[{"label": s, "value": s} for s in list_all_sensors()],
            value=_resolve_sensor_id("grid_consumption") or None,
            placeholder="Select sensor..."
        ),
        _sensor_value_readout("set-sens-grid-read", _resolve_sensor_id("grid_consumption")),
        html.Label("Grid feed-in", style={"marginTop": "12px"}),
        dcc.Dropdown(
            id="set-sens-feed",
            options=[{"label": s, "value": s} for s in list_all_sensors()],
            value=_resolve_sensor_id("grid_feed_in") or None,
            placeholder="Select sensor..."
        ),
        _sensor_value_readout("set-sens-feed-read", _resolve_sensor_id("grid_feed_in")),
        html.Div([
            html.Button("Save sensors", id="set-sens-save", className="custom-tab", style={"marginTop": "12px"}),
            html.Span(id="set-sens-status", className="settings-status", style={"marginLeft": "10px"}),
        ], className="settings-page-actions"),
    ]),

    # --- NEW: ELECTRICITY (second) ---
    _section("Electricity", [
        html.Div([
            html.Label("Pricing mode"),
            html.Div([
                dcc.Checklist(
                    id="set-elec-fixed-active",
                    options=[{"label": " Fixed price", "value": "on"}],
                    value=(["on"] if ((elec_get("pricing_mode","") or "").lower() or
                                      ("dynamic" if elec_resolve("current_electricity_price") else "fixed")) == "fixed" else [])
                ),
                dcc.Checklist(
                    id="set-elec-dyn-active",
                    options=[{"label": " Dynamic (sensor)", "value": "on"}],
                    value=(["on"] if ((elec_get("pricing_mode","") or "").lower() or
                                      ("dynamic" if elec_resolve("current_electricity_price") else "fixed")) == "dynamic" else [])
                ),
            ], style={"display": "flex", "gap": "18px", "alignItems": "center"})
        ], style={"marginBottom": "10px"}),

        # dynamic row
        html.Div([
            html.Label("Dynamic price sensor"),
            dcc.Dropdown(
                id="sensor-current-electricity-price",
                options=[{"label": s, "value": s} for s in list_all_sensors()],
                value=elec_resolve("current_electricity_price") or None,
                placeholder="Select sensor..."
            ),
            _sensor_value_readout("sensor-current-electricity-price-read", elec_resolve("current_electricity_price")),
        ], id="set-elec-row-sensor", style={"marginTop": "6px"}),

        # fixed row
        html.Div([
            html.Label("Fixed price value (per kWh)"),
            number_stepper("elec-fixed-value", float(elec_get("fixed_price_value", 0.0) or 0.0), step=0.0001, min=0, max=2, width_px=140),
        ], id="set-elec-row-fixed", style={"marginTop": "6px"}),

        html.Hr(),

        html.Div([
            html.Label("Network fee (down / import)"),
            number_stepper("elec-fee-down", float(elec_get("network_fee_down_value", 0.0) or 0.0), step=0.0001, min=0, max=2, width_px=140),
            html.Span(" "),
            html.Label("Network fee (up / export)", style={"marginLeft": "16px"}),
            number_stepper("elec-fee-up", float(elec_get("network_fee_up_value", 0.0) or 0.0), step=0.0001, min=0, max=2, width_px=140),
        ], style={"marginTop": "6px"}),

        html.Div([
            html.Button("Save electricity", id="set-elec-save", className="custom-tab", style={"marginTop": "12px"}),
            html.Span(id="set-elec-status", className="settings-status", style={"marginLeft": "10px"}),
        ], className="settings-page-actions"),
    ]),


        _section("Cooling circuit / Miners", [
            dcc.Checklist(
                id="set-cooling-enabled",
                options=[{"label": " Cooling circuit feature active", "value": "on"}],
                value=(["on"] if cooling_enabled else []),
            ),
            html.Div(
                "If enabled, a Cooling block appears in the Miners tab. "
                "Miners with 'Cooling required' can only switch on when Cooling ready/state is TRUE.",
                style={"opacity": 0.8, "marginTop": "6px"}
            ),

            html.Div([
                html.Label("Cooling start threshold (fraction)"),
                number_stepper("set-cooling-on-frac", cool_on_frac, step=0.01, min=0, max=1, width_px=140),
                html.Span("  (0.50 = 50 %)", style={"opacity": 0.7, "marginLeft": "6px"}),
            ], style={"marginTop": "8px"}),

            html.Div([
                html.Label("Miner start threshold (fraction)"),
                number_stepper("set-miner-on-frac", miner_on_frac, step=0.01, min=0, max=1, width_px=140),
                html.Span("  (z. B. 0.10 = 10 %)", style={"opacity": 0.7, "marginLeft": "6px"}),
            ], style={"marginTop": "8px"}),

            html.Div([
                html.Label("Cooling minimum runtime after ON (s)"),
                number_stepper("set-cooling-min-run-s", cool_min_run, step=1, min=0, width_px=140),
            ], style={"marginTop": "8px"}),

            html.Div([
                html.Label("Cooling minimum OFF time after OFF (s)"),
                number_stepper("set-cooling-min-off-s", cool_min_off, step=1, min=0, width_px=140),
            ], style={"marginTop": "8px"}),

            html.Hr(),

            html.Div([
                html.Label("Miner profit ON threshold (€/h)"),
                number_stepper("set-miner-on-margin", miner_on_margin, step=0.01, width_px=140),
                html.Span("  (≥ this to switch ON)", style={"opacity": 0.7, "marginLeft": "6px"}),
            ], style={"marginTop": "6px"}),

            html.Div([
                html.Label("Miner profit OFF threshold (€/h)"),
                number_stepper("set-miner-off-margin", miner_off_margin, step=0.01, width_px=140),
                html.Span("  (≤ this to switch OFF; can be negative)", style={"opacity": 0.7, "marginLeft": "6px"}),
            ], style={"marginTop": "8px"}),

            html.Div([
                html.Label("Minimum runtime after ON (s)"),
                number_stepper("set-miner-min-run-s", miner_min_run_s, step=1, min=0, width_px=140),
                html.Span("  (debounce to avoid flapping)", style={"opacity": 0.7, "marginLeft": "6px"}),
            ], style={"marginTop": "8px"}),

            html.Div([
                html.Label("Minimum OFF time after OFF (s)"),
                number_stepper("set-miner-min-off-s", miner_min_off_s, step=1, min=0, width_px=140),
            ], style={"marginTop": "8px"}),
        ]),

        _section("PV-cost-model", [
            dcc.RadioItems(
                id="set-pv-policy",
                options=[
                    {"label": " PV = 0 €/kWh", "value": "zero"},
                    {"label": " PV = Feed-in tariff − network-fee (up)", "value": "feedin"},
                ],
                value=policy,
                labelStyle={"display": "block", "marginBottom": "6px"}
            ),

            html.Div([
                html.Label("Source for Feed-in tariff"),
                dcc.RadioItems(
                    id="set-feedin-mode",
                    options=[
                        {"label": " fixed Value", "value": "fixed"},
                        {"label": " Sensor", "value": "sensor"},
                    ],
                    value=mode,
                    labelStyle={"display": "inline-block", "marginRight": "18px"}
                ),
            ], id="row-feed-mode", style={"marginTop": "6px", "display": ("block" if policy == "feedin" else "none")}),

            html.Div([
                html.Label("Feed-in tariff (€/kWh)"),
                dcc.Input(
                    id="set-feedin-value", type="number", step=0.000001, value=fi_val,
                    style=_input_style(220)  # <—
                ),
            ], id="row-feed-fixed", style={"marginTop": "6px", "display": (
                "block" if (policy == "feedin" and mode == "fixed") else "none")}),

            html.Div([
                html.Label("Feed-in tariff-Sensor"),
                dcc.Dropdown(
                    id="set-feedin-sensor",
                    options=sensors, value=fi_sens or None, placeholder="select Sensor...",
                    style=_input_style(260)  # <— Rahmen um den Container
                ),
                _sensor_value_readout("set-feedin-sensor-read", fi_sens),
            ], id="row-feed-sensor", style={"marginTop": "6px", "display": (
                "block" if (policy == "feedin" and mode == "sensor") else "none")}),

            html.Div(
                id="set-pv-effective",
                style={"marginTop": "8px", "fontWeight": "bold", "opacity": 0.9},
                children=f"Currently assumed PV-Costs: {eff_pv_cost:.4f} €/kWh"
            ),
        ]),

        # ---------- NEW: Planner guard ----------
        _section("Planner guard (anti-overdraw)", [
            html.Div([
                html.Label("Fixed safety margin (W)"),
                number_stepper("set-guard-w", guard_w, step=1, min=0, width_px=160),
                html.Span("  (subtracts this from measured PV surplus)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "6px"}),

            html.Div([
                html.Label("Relative safety margin (fraction)"),
                number_stepper("set-guard-pct", guard_pct, step=0.001, min=0, max=0.2, width_px=160),
                html.Span("  e.g. 0.03 = 3 %  (values >1 are interpreted as percent and divided by 100 on save)",
                          style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "8px"}),
        ]),

        _section("Export cap boost", [
            html.Div([
                html.Label("Grid export cap (kW)"),
                number_stepper("set-export-cap", export_cap, step=0.1, min=0, width_px=140),
                html.Span(" (z. B. 5.0)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "6px"}),
            html.Div([
                html.Label("Boost cooldown (s)"),
                number_stepper("set-boost-cooldown", boost_cooldown, step=1, min=5, width_px=140),
                html.Span(" (Beruhigungszeit nach Zuschalten)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "8px"}),
        ]),

        _section("PV ramp-up", [
            dcc.Checklist(
                id="set-allow-pv-ramp-up",
                options=[{"label": " Allow PV ramp up", "value": "on"}],
                value=(["on"] if allow_pv_ramp_up else []),
                style={"marginBottom": "8px"}
            ),
            html.Div(
                "Learns a virtual PV bonus behind the export limit by probing with the water heater. "
                "The stable bonus is then used globally by the planner.",
                style={"opacity": 0.8, "marginBottom": "10px"}
            ),
            html.Div([
                html.Label("Settle time (s)"),
                number_stepper("set-pv-ramp-settle", pv_ramp_settle_s, step=1, min=10, width_px=140),
                html.Span("  (e.g. 60 = 1 min before a learned bonus becomes global)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "6px"}),
            html.Div([
                html.Label("Import hysteresis (W)"),
                number_stepper("set-pv-ramp-hysteresis", pv_ramp_hysteresis_w, step=1, min=0, width_px=140),
                html.Span("  (import above this reduces the learned bonus)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "8px"}),
            html.Div([
                html.Label("Probe step up (kW)"),
                number_stepper("set-pv-ramp-step-up", pv_ramp_step_up_kw, step=0.01, min=0, width_px=140),
                html.Span("  (extra heater load per planner tick while probing)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "8px"}),
            html.Div([
                html.Label("Safety step down (kW)"),
                number_stepper("set-pv-ramp-step-down", pv_ramp_step_down_kw, step=0.01, min=0, width_px=140),
                html.Span("  (minimum reduction when grid import appears)", style={"marginLeft": "8px", "opacity": 0.7}),
            ], style={"marginTop": "8px"}),
        ]),

        _section("Bitcoin-economics", [
            html.Div([
                html.Div([
                    html.Label("BTC-Price-Currency"),
                    dcc.Dropdown(
                        id="set-btc-currency",
                        options=[{"label": "EUR", "value": "EUR"}, {"label": "USD", "value": "USD"}],
                        value=currency,
                        clearable=False,
                        style={"width": "120px"}
                    ),
                    html.Span(id="set-fx-read", style={"marginLeft": "14px"}),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "alignItems": "center"}),
                html.Div([
                    html.Label("Block reward (BTC)"),
                    number_stepper("set-reward", reward, step=0.0001, width_px=140),
                ], style={"display": "flex", "flexDirection": "column", "gap": "6px", "marginTop": "12px"}),
                html.Div([
                    html.Label("Tax rate %"),
                    number_stepper("set-tax", tax_pct, step=0.1, width_px=140),
                ], style={"display": "flex", "flexDirection": "column", "gap": "6px", "marginTop": "12px"}),
            ], style={"display": "flex", "flexDirection": "column"})
        ]),

        _section("Dashboard / Sankey", [
            html.Div("Show all lanes in chart (also shows inactive lanes if the feature is enabled):",
                     style={"marginBottom": "6px", "opacity": 0.85}),

            dcc.Checklist(
                id="ui-show-inactive-desktop",
                options=[{"label": " Desktop", "value": "on"}],
                value=(["on"] if bool(set_get("ui_show_inactive_desktop", True)) else []),
                style={"marginBottom": "4px"}
            ),
            dcc.Checklist(
                id="ui-show-inactive-tablet",
                options=[{"label": " Tablet", "value": "on"}],
                value=(["on"] if bool(set_get("ui_show_inactive_tablet", True)) else []),
                style={"marginBottom": "4px"}
            ),
            dcc.Checklist(
                id="ui-show-inactive-phone",
                options=[{"label": " Phone", "value": "on"}],
                value=(["on"] if bool(set_get("ui_show_inactive_phone", True)) else []),
                style={"marginBottom": "8px"}
            ),

            html.Div("What to include when showing inactive lanes:", style={"marginTop": "6px", "opacity": 0.85}),
            dcc.Checklist(
                id="ui-show-src-inactive",
                options=[{"label": " Sources (PV, Grid, Battery discharge)", "value": "on"}],
                value=(["on"] if bool(set_get("ui_show_inactive_sources", True)) else []),
                style={"marginBottom": "4px"}
            ),
            dcc.Checklist(
                id="ui-show-sink-inactive",
                options=[
                    {"label": " Sinks (Miners, Heater, Wallbox, Battery charge, Feed-in, Cooling)", "value": "on"}],
                value=(["on"] if bool(set_get("ui_show_inactive_sinks", True)) else []),
            ),
        ]),

        html.Div([
            html.Button("Save", id="set-save", className="custom-tab", style={"marginTop": "12px"}),
            html.Span(id="set-status", className="settings-status", style={"marginLeft": "10px"}),
        ], className="settings-page-actions"),

        _section("Power draw priority", [
            html.P(
                "The planner prefers this order when enough power is available. Cooling is handled implicitly by miners that require it. Use ↑/↓ to reorder — it’s saved automatically.",
                className="settings-subtle-text",
            ),
            html.Div(id="prio-list", className="prio-list"),
            html.Div(id="prio-status", className="settings-status", style={"marginTop": "6px"}),
        ]),
        footer_license(),
    ], className="settings-page")


# --------------------------------
# Callbacks
# --------------------------------

def register_callbacks(app):

    @app.callback(
        Output("set-sens-pv-read", "children"),
        Output("set-sens-grid-read", "children"),
        Output("set-sens-feed-read", "children"),
        Output("sensor-current-electricity-price-read", "children"),
        Output("set-feedin-sensor-read", "children"),
        Input("set-sensor-values-interval", "n_intervals"),
        Input("set-sens-pv", "value"),
        Input("set-sens-grid", "value"),
        Input("set-sens-feed", "value"),
        Input("sensor-current-electricity-price", "value"),
        Input("set-feedin-sensor", "value"),
        prevent_initial_call=False,
    )
    def _refresh_sensor_readouts(_tick, pv_sensor, grid_sensor, feed_sensor, elec_sensor, feedin_sensor):
        return (
            _sensor_value_text(pv_sensor),
            _sensor_value_text(grid_sensor),
            _sensor_value_text(feed_sensor),
            _sensor_value_text(elec_sensor),
            _sensor_value_text(feedin_sensor),
        )

    # ----------------------------
    # SENSORS: Save mapping
    # ----------------------------
    @app.callback(
        Output("set-sens-status", "children"),
        Input("set-sens-save", "n_clicks"),
        State("set-sens-pv", "value"),
        State("set-sens-grid", "value"),
        State("set-sens-feed", "value"),
        prevent_initial_call=True
    )
    def _save_sensors(n, pv, grid, feed):
        if not n:
            raise PreventUpdate
        mapping = {
            "pv_production": pv or "",
            "grid_consumption": grid or "",
            "grid_feed_in": feed or "",
        }
        # Write to sensors.local.yaml (keeps old resolver paths working)
        save_yaml(SENS_OVR, {"mapping": mapping})

        # Mirror to pv_mining_local_config.yaml for backwards compatibility
        cfg = load_yaml(MAIN_CFG, {})
        cfg.setdefault("entities", {})
        cfg["entities"]["sensor_pv_production"]   = pv or ""
        cfg["entities"]["sensor_grid_consumption"] = grid or ""
        cfg["entities"]["sensor_grid_feed_in"]     = feed or ""
        save_yaml(MAIN_CFG, cfg)
        return "Sensors saved!"

    # ----------------------------
    # ELECTRICITY: toggle visibility / exclusivity
    # ----------------------------
    @app.callback(
        Output("set-elec-fixed-active", "value"),
        Output("set-elec-dyn-active", "value"),
        Output("sensor-current-electricity-price", "disabled"),
        Output("elec-fixed-value", "disabled"),
        Output("set-elec-row-sensor", "style"),
        Output("set-elec-row-fixed", "style"),
        Input("set-elec-fixed-active", "value"),
        Input("set-elec-dyn-active", "value"),
        prevent_initial_call=True
    )
    def _toggle_elec_mode(fixed_val, dyn_val):
        fixed_on = bool(fixed_val and "on" in fixed_val)
        dyn_on   = bool(dyn_val and "on" in dyn_val)

        ctx = dash.callback_context
        if fixed_on and dyn_on:
            # last click wins
            who = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
            if who == "set-elec-fixed-active":
                dyn_on = False
            else:
                fixed_on = False
        elif not fixed_on and not dyn_on:
            fixed_on = True  # fallback

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

    # ----------------------------
    # ELECTRICITY: save
    # ----------------------------
    @app.callback(
        Output("set-elec-status", "children"),
        Input("set-elec-save", "n_clicks"),
        State("set-elec-fixed-active", "value"),
        State("set-elec-dyn-active", "value"),
        State("sensor-current-electricity-price", "value"),
        State("elec-fixed-value", "value"),
        State("elec-fee-down", "value"),
        State("elec-fee-up", "value"),
        prevent_initial_call=True
    )
    def _save_electricity(n, fixed_val, dyn_val, sensor_id, fixed_price, fee_down, fee_up):
        if not n:
            raise PreventUpdate

        fixed_on = bool(fixed_val and "on" in fixed_val)
        dyn_on   = bool(dyn_val and "on" in dyn_val)
        if fixed_on and dyn_on:
            # prefer the last selection; here: dynamic wins
            fixed_on, dyn_on = False, True
        if not fixed_on and not dyn_on:
            fixed_on = True

        pricing_mode = "fixed" if fixed_on else "dynamic"

        # write mapping always (harmless when fixed)
        elec_set_mapping("current_electricity_price", sensor_id or "")

        # persist variables
        elec_set_vars(
            pricing_mode=pricing_mode,
            fixed_price_value=float(fixed_price or 0.0),
            network_fee_down_value=float(fee_down or 0.0),
            network_fee_up_value=float(fee_up or 0.0),
        )
        return "Electricity settings saved!"


    # Sichtbarkeit PV-Inputreihen
    @app.callback(
        Output("row-feed-mode", "style"),
        Output("row-feed-fixed", "style"),
        Output("row-feed-sensor", "style"),
        Input("set-pv-policy", "value"),
        Input("set-feedin-mode", "value"),
        prevent_initial_call=False
    )
    def _vis(policy, mode):
        show_feed = (policy == "feedin")
        st_mode = {"marginTop": "6px", "display": "block" if show_feed else "none"}
        st_fixed = {"marginTop": "6px", "display": "block" if (show_feed and mode == "fixed") else "none"}
        st_sensor = {"marginTop": "6px", "display": "block" if (show_feed and mode == "sensor") else "none"}
        return st_mode, st_fixed, st_sensor

    # Effektive PV-Kosten (nur Anzeige)
    @app.callback(
        Output("set-pv-effective", "children"),
        Input("set-pv-policy", "value"),
        Input("set-feedin-mode", "value"),
        Input("set-feedin-value", "value"),
        Input("set-feedin-sensor", "value"),
    )
    def _pv_effective(policy, mode, val, sens):
        fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
        if policy == "feedin":
            tarif = _num(val, 0.0) if mode == "fixed" else _num(get_sensor_value(sens) if sens else 0.0, 0.0)
            eff = max(tarif - fee_up, 0.0)
        else:
            eff = 0.0
        return f"Currently assumed PV-Costs: {eff:.4f} €/kWh"

    # Settings speichern
    @app.callback(
        Output("set-status", "children"),
        Input("set-save", "n_clicks"),
        State("set-pv-policy", "value"),
        State("set-feedin-mode", "value"),
        State("set-feedin-value", "value"),
        State("set-feedin-sensor", "value"),
        State("set-btc-currency", "value"),
        State("set-reward", "value"),
        State("set-tax", "value"),
        State("set-cooling-enabled", "value"),
        State("set-guard-w", "value"),
        State("set-guard-pct", "value"),
        State("set-miner-on-margin", "value"),
        State("set-miner-off-margin", "value"),
        State("set-miner-min-run-s", "value"),
        State("set-miner-min-off-s", "value"),
        State("ui-show-inactive-desktop", "value"),
        State("ui-show-inactive-tablet", "value"),
        State("ui-show-inactive-phone", "value"),
        State("ui-show-src-inactive", "value"),
        State("ui-show-sink-inactive", "value"),
        State("set-export-cap", "value"),
        State("set-boost-cooldown", "value"),
        State("set-allow-pv-ramp-up", "value"),
        State("set-pv-ramp-settle", "value"),
        State("set-pv-ramp-hysteresis", "value"),
        State("set-pv-ramp-step-up", "value"),
        State("set-pv-ramp-step-down", "value"),
        State("set-cooling-on-frac", "value"),
        State("set-miner-on-frac", "value"),
        State("set-cooling-min-run-s", "value"),
        State("set-cooling-min-off-s", "value"),

        prevent_initial_call=True
    )
    def _save(n, policy, mode, val, sens, cur, reward, tax, cool_enabled_val,
              guard_w, guard_pct,
              miner_on_margin, miner_off_margin, miner_min_run_s, miner_min_off_s,
              show_desktop, show_tablet, show_phone, show_src, show_sink, export_cap, boost_cooldown,
              allow_pv_ramp_up_val, pv_ramp_settle_s, pv_ramp_hysteresis_w, pv_ramp_step_up_kw, pv_ramp_step_down_kw,
              cool_on_frac, miner_on_frac, cool_min_run_s, cool_min_off_s):
        if not n:
            return ""
        # Prozent robust interpretieren: 3 -> 0.03
        g_pct_raw = _num(guard_pct, 0.0)
        g_pct = g_pct_raw / 100.0 if g_pct_raw > 1.0 else g_pct_raw
        g_pct = max(0.0, min(0.2, g_pct))  # clamp 0–20%
        ui_show_inactive_desktop = bool(show_desktop and "on" in show_desktop)
        ui_show_inactive_tablet = bool(show_tablet and "on" in show_tablet)
        ui_show_inactive_phone = bool(show_phone and "on" in show_phone)
        ui_show_inactive_sources = bool(show_src and "on" in show_src)
        ui_show_inactive_sinks = bool(show_sink and "on" in show_sink)

        set_set(
            pv_cost_policy=(policy or "zero"),
            feedin_price_mode=(mode or "fixed"),
            feedin_price_value=_num(val, 0.0),
            feedin_price_sensor=(sens or ""),
            btc_price_currency=(cur or "EUR"),
            block_reward_btc=_num(reward, 3.125),
            sell_tax_percent=_num(tax, 0.0),
            cooling_feature_enabled=bool(cool_enabled_val and "on" in cool_enabled_val),
            surplus_guard_w=_num(guard_w, 0.0),
            surplus_guard_pct=g_pct,
            miner_profit_on_eur_h=_num(miner_on_margin, 0.05),
            miner_profit_off_eur_h=_num(miner_off_margin, -0.01),
            miner_min_run_s=int(_num(miner_min_run_s, 30)),
            miner_min_off_s=int(_num(miner_min_off_s, 20)),
            ui_show_inactive_desktop=ui_show_inactive_desktop,
            ui_show_inactive_tablet=ui_show_inactive_tablet,
            ui_show_inactive_phone=ui_show_inactive_phone,
            ui_show_inactive_sources=ui_show_inactive_sources,
            ui_show_inactive_sinks=ui_show_inactive_sinks,
            grid_export_cap_kw=_num(export_cap, 0.0),
            boost_cooldown_s=int(_num(boost_cooldown, 30)),
            allow_pv_ramp_up=bool(allow_pv_ramp_up_val and "on" in allow_pv_ramp_up_val),
            pv_ramp_settle_s=max(10, int(_num(pv_ramp_settle_s, 60))),
            pv_ramp_hysteresis_w=max(0.0, _num(pv_ramp_hysteresis_w, 200.0)),
            pv_ramp_step_up_kw=max(0.0, _num(pv_ramp_step_up_kw, 0.40)),
            pv_ramp_step_down_kw=max(0.0, _num(pv_ramp_step_down_kw, 0.60)),
            pv_ramp_cap_epsilon_kw=max(0.0, _num(set_get("pv_ramp_cap_epsilon_kw", 0.05), 0.05)),
            cooling_on_fraction=max(0.0, min(1.0, _num(cool_on_frac, 0.50))),
            miner_on_fraction=max(0.0, min(1.0, _num(miner_on_frac, _num(set_get("discrete_on_fraction", 0.95), 0.95)))),
            cooling_min_run_s=int(_num(cool_min_run_s, 20)),
            cooling_min_off_s=int(_num(cool_min_off_s, 20)),
        )
        shown_pct = g_pct * 100.0
        return (f"Saved. Planner guard = {guard_w or 0:.0f} W and {shown_pct:.2f} %. "
                f"ShowAll lanes: D={int(ui_show_inactive_desktop)} T={int(ui_show_inactive_tablet)} P={int(ui_show_inactive_phone)}; "
                f"src={int(ui_show_inactive_sources)} sink={int(ui_show_inactive_sinks)}.  "
                f"Miner tuning: on≥{_num(miner_on_margin, 0.05):.2f} €/h, "
                f"off≤{_num(miner_off_margin, -0.01):.2f} €/h, "
                f"minRun={int(_num(miner_min_run_s, 30))} s, "
                f"minOff={int(_num(miner_min_off_s, 20))} s."
                f" PV ramp={int(bool(allow_pv_ramp_up_val and 'on' in allow_pv_ramp_up_val))}, "
                f"settle={max(10, int(_num(pv_ramp_settle_s, 60)))} s, "
                f"hys={max(0.0, _num(pv_ramp_hysteresis_w, 200.0)):.0f} W, "
                f"up={max(0.0, _num(pv_ramp_step_up_kw, 0.40)):.2f} kW, "
                f"down={max(0.0, _num(pv_ramp_step_down_kw, 0.60)):.2f} kW."
                f" Cooling frac={_num(cool_on_frac, 0.5):.2f}, "
                f" Miner frac={_num(miner_on_frac, 0.95):.2f}, "
                f" CminRun={int(_num(cool_min_run_s, 20))} s, "
                f" CminOff={int(_num(cool_min_off_s, 20))} s. ")

    # Store befüllen/aktualisieren, wenn Settings-Tab angezeigt wird
    @app.callback(
        Output("prio-list", "children"),
        Output("prio-status", "children", allow_duplicate=True),
        Input("tabs-content", "children"),
        Input("set-cooling-enabled", "value"),
        prevent_initial_call=True
    )
    def _hydrate_and_render(_children, cooling_toggle):
        available = _prio_available_items()
        order = _prio_merge_with_stored(_load_prio_ids(), available)

        by_id = {a["id"]: a for a in available}
        rows = []
        for idx, pid in enumerate(order):
            if pid not in by_id:
                continue
            rows.append(_prio_row(by_id[pid], idx, order))
        return rows, ""

    # ↑/↓ – Autosave
    @app.callback(
        Output("prio-list", "children", allow_duplicate=True),
        Output("prio-status", "children", allow_duplicate=True),
        Input({"type": "prio-move-up", "index": ALL}, "n_clicks"),
        Input({"type": "prio-move-down", "index": ALL}, "n_clicks"),
        prevent_initial_call=True
    )
    def _move_and_save(_ups, _downs):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trig = ctx.triggered_id  # dict: {"type":"prio-move-up/down","index": i}
        if not isinstance(trig, dict):
            raise PreventUpdate

        available = _prio_available_items()
        current = _prio_merge_with_stored(_load_prio_ids(), available)

        # Grenzen: grid_feed bleibt unten
        last_idx = len(current) - 1
        last_movable = last_idx - 1 if (current and current[-1] == "grid_feed") else last_idx

        i = int(trig.get("index", -1))
        if i < 0 or i >= len(current):
            raise PreventUpdate

        if trig.get("type") == "prio-move-up":
            if i == 0 or current[i] == "grid_feed":
                raise PreventUpdate
            current[i-1], current[i] = current[i], current[i-1]

        elif trig.get("type") == "prio-move-down":
            if current[i] == "grid_feed" or i >= last_movable:
                raise PreventUpdate
            current[i], current[i+1] = current[i+1], current[i]

        # grid_feed sicher ans Ende
        if "grid_feed" in current:
            current = [x for x in current if x != "grid_feed"] + ["grid_feed"]

        _save_prio_ids(current)

        # Neu rendern
        by_id = {a["id"]: a for a in available}
        rows = []
        for idx, pid in enumerate(current):
            if pid not in by_id:
                continue
            rows.append(_prio_row(by_id[pid], idx, current))
        return rows, "Priority saved!"

# Exporte, damit main.py (falls nötig) darauf zugreifen kann
_prio_available_items = _prio_available_items
_prio_merge_with_stored = _prio_merge_with_stored
_load_prio_ids = _load_prio_ids
