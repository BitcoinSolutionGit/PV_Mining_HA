# ui_pages/settings.py
import json
import dash

from dash import html, dcc, callback_context
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from services.settings_store import get_var as set_get, set_vars as set_set
from services.electricity_store import get_var as elec_get
from services.ha_sensors import list_all_sensors, get_sensor_value
from services.forex import usd_to_eur_rate
from services.miners_store import list_miners

PRIO_KEY = "priority_order"               # Liste
PRIO_KEY_JSON = "priority_order_json"     # JSON-Fallback

PRIO_COLORS = {
    "inflow":    "#FFD700",
    "cooling":   "#5DADE2",
    "miners":    "#FF9900",
    "battery":   "#8E44AD",
    "heater":    "#3399FF",
    "wallbox":   "#33CC66",
    "grid_feed": "#FF3333",
    "load":      "#A0A0A0",
    "inactive":  "#DDDDDD",
}

# ---------- Helpers ----------

def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d

def _prio_available_items():
    items = []
    if bool(set_get("cooling_feature_enabled", False)):
        items.append({"id": "cooling", "label": "Cooling circuit", "color": PRIO_COLORS["cooling"]})
    try:
        for m in (list_miners() or []):
            items.append({
                "id": f"miner:{m['id']}",
                "label": m.get("name", "Miner"),
                "color": PRIO_COLORS["miners"],
            })
    except Exception:
        pass
    items += [
        {"id": "battery",   "label": "Battery",      "color": PRIO_COLORS["battery"]},
        {"id": "wallbox",   "label": "Wallbox",      "color": PRIO_COLORS["wallbox"]},
        {"id": "heater",    "label": "Water Heater", "color": PRIO_COLORS["heater"]},
        {"id": "house",     "label": "House load",   "color": PRIO_COLORS["load"]},
        {"id": "grid_feed", "label": "Grid feed-in", "color": PRIO_COLORS["grid_feed"]},
    ]
    # dedupe
    seen, dedup = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"]); dedup.append(it)
    return dedup

def _prio_merge_with_stored(stored_ids, available):
    avail_ids = [a["id"] for a in available]
    order = [x for x in (stored_ids or []) if x in avail_ids]
    for aid in avail_ids:
        if aid not in order and aid != "grid_feed":
            order.append(aid)
    if "grid_feed" in avail_ids:
        order = [x for x in order if x != "grid_feed"] + ["grid_feed"]
    return order

def _load_prio_ids():
    raw = set_get(PRIO_KEY, None)
    if isinstance(raw, list):
        return raw
    raw_json = set_get(PRIO_KEY_JSON, "")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            val = json.loads(raw_json)
            if isinstance(val, list):
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

def _prio_row(item):
    return html.Div(
        [
            html.Span("", style={
                "display":"inline-block","width":"10px","height":"10px",
                "borderRadius":"50%","backgroundColor": item.get("color","#ccc"),
                "marginRight":"8px","verticalAlign":"middle"
            }),
            html.Strong(item.get("label","")),
        ],
        className="prio-item",
        **{"data-pid": item["id"], "draggable": "true"}
    )

def _render_prio_children(order):
    available = _prio_available_items()
    if not order:
        order = _prio_merge_with_stored(_load_prio_ids(), available)
    by_id = {a["id"]: a for a in available}
    out = [by_id[i] for i in order if i in by_id]
    for a in available:
        if a["id"] not in order and a["id"] != "grid_feed":
            out.append(a)
    if "grid_feed" in by_id and all(x["id"] != "grid_feed" for x in out):
        out.append(by_id["grid_feed"])
    return [_prio_row(x) for x in out]

# ---------- Layout ----------

def layout():
    policy   = (set_get("pv_cost_policy", "zero") or "zero").lower()
    mode     = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fi_val   = _num(set_get("feedin_price_value", 0.0), 0.0)
    fi_sens  = set_get("feedin_price_sensor", "") or ""
    currency = (set_get("btc_price_currency", "EUR") or "EUR").upper()
    reward   = _num(set_get("block_reward_btc", 3.125), 3.125)
    tax_pct  = _num(set_get("sell_tax_percent", 0.0), 0.0)

    sensors = [{"label": s, "value": s} for s in list_all_sensors()]

    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    eff_pv_cost = max((fi_val if mode=="fixed" else _num(get_sensor_value(fi_sens), 0.0)) - fee_up, 0.0) if policy=="feedin" else 0.0
    cooling_enabled = bool(set_get("cooling_feature_enabled", False))

    return html.Div([
        html.H2("Settings"),

        html.Fieldset([
            html.Legend("Cooling Circuit"),
            dcc.Checklist(
                id="set-cooling-enabled",
                options=[{"label": " Cooling circuit feature active", "value": "on"}],
                value=(["on"] if cooling_enabled else []),
            ),
            html.Div("If enabled, a Cooling block appears in the Miners tab. "
                     "Miners with 'Cooling required' can only be turned on when Cooling is running.",
                     style={"opacity": 0.8, "marginTop": "6px"})
        ], style={"border": "1px solid #ccc", "borderRadius": "8px", "padding": "10px", "marginBottom": "14px"}),

        html.Fieldset([
            html.Legend("PV-cost-model"),
            dcc.RadioItems(
                id="set-pv-policy",
                options=[
                    {"label": " PV = 0 €/kWh", "value": "zero"},
                    {"label": " PV = Feed-in tariff − network-fee (up)", "value": "feedin"},
                ],
                value=policy,
                labelStyle={"display":"block", "marginBottom":"6px"}
            ),

            html.Div([
                html.Label("Source for Feed-in tariff"),
                dcc.RadioItems(
                    id="set-feedin-mode",
                    options=[
                        {"label":" fixed Value", "value":"fixed"},
                        {"label":" Sensor",      "value":"sensor"},
                    ],
                    value=mode,
                    labelStyle={"display":"inline-block", "marginRight":"18px"}
                ),
            ], id="row-feed-mode", style={"marginTop":"6px", "display": ("block" if policy=="feedin" else "none")}),

            html.Div([
                html.Label("Feed-in tariff (€/kWh)"),
                dcc.Input(id="set-feedin-value", type="number", step=0.000001, value=fi_val, style={"width":"220px"}),
            ], id="row-feed-fixed", style={"marginTop":"6px", "display": ("block" if (policy=="feedin" and mode=="fixed") else "none")}),

            html.Div([
                html.Label("Feed-in tariff sensor"),
                dcc.Dropdown(id="set-feedin-sensor", options=sensors, value=fi_sens or None, placeholder="select Sensor..."),
            ], id="row-feed-sensor", style={"marginTop":"6px", "display": ("block" if (policy=="feedin" and mode=="sensor") else "none")}),

            html.Div(id="set-pv-effective", style={"marginTop":"8px", "fontWeight":"bold", "opacity":0.9},
                     children=f"Currently assumed PV-Costs: {eff_pv_cost:.4f} €/kWh"),
        ], style={"border":"1px solid #ccc", "borderRadius":"8px", "padding":"10px", "marginBottom":"14px"}),

        html.Fieldset([
            html.Legend("Bitcoin-economics"),
            html.Div([
                html.Label("BTC-Price-Currency"),
                dcc.Dropdown(
                    id="set-btc-currency",
                    options=[{"label":"EUR", "value":"EUR"}, {"label":"USD", "value":"USD"}],
                    value=currency, clearable=False, style={"width":"140px"}
                ),
                html.Span(id="set-fx-read", style={"marginLeft":"14px"}),

                html.Span("  "),
                html.Label("Block reward (BTC)", style={"marginLeft":"16px"}),
                dcc.Input(id="set-reward", type="number", step=0.0001, value=reward, style={"width":"120px"}),

                html.Span("  "),
                html.Label("Tax rate %", style={"marginLeft":"16px"}),
                dcc.Input(id="set-tax", type="number", step=0.1, value=tax_pct, style={"width":"100px"}),
            ], style={"display":"flex","flexWrap":"wrap","gap":"10px","alignItems":"center"})
        ], style={"border":"1px solid #ccc", "borderRadius":"8px", "padding":"10px"}),

        html.Button("Save", id="set-save", className="custom-tab", style={"marginTop":"12px"}),
        html.Span(id="set-status", style={"marginLeft":"10px", "color":"green"}),

        html.Hr(),
        html.H3("Power draw priority"),
        html.P("Drag & drop to reorder (top = highest priority). Grid feed-in is always last."),

        # Hidden wire: wird vom assets/prio_dnd.js beim Drop befüllt (JSON Liste)
        dcc.Input(id="prio-dnd-wire", type="text", value="", style={"display": "none"}),

        html.Div(id="prio-list", className="prio-list"),

        html.Div([
            html.Button("Save priority", id="prio-save", className="custom-tab"),
            html.Button("Reset to default", id="prio-reset", className="custom-tab", style={"marginLeft": "10px"}),
            html.Span(id="prio-status", style={"marginLeft": "12px", "color": "green"})
        ], style={"marginTop": "8px"}),
    ])

# ---------- Callbacks ----------

def register_callbacks(app):
    # Sichtbarkeit Feed-in Controls
    @app.callback(
        Output("row-feed-mode","style"),
        Output("row-feed-fixed","style"),
        Output("row-feed-sensor","style"),
        Input("set-pv-policy","value"),
        Input("set-feedin-mode","value"),
        prevent_initial_call=False
    )
    def _vis(policy, mode):
        show_feed = (policy == "feedin")
        st_mode   = {"marginTop":"6px", "display": "block" if show_feed else "none"}
        st_fixed  = {"marginTop":"6px", "display": "block" if (show_feed and mode=="fixed") else "none"}
        st_sensor = {"marginTop":"6px", "display": "block" if (show_feed and mode=="sensor") else "none"}
        return st_mode, st_fixed, st_sensor

    # PV-Kosten-Text live
    @app.callback(
        Output("set-pv-effective","children"),
        Input("set-pv-policy","value"),
        Input("set-feedin-mode","value"),
        Input("set-feedin-value","value"),
        Input("set-feedin-sensor","value"),
    )
    def _pv_effective(policy, mode, val, sens):
        fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
        if policy == "feedin":
            tarif = _num(val, 0.0) if mode == "fixed" else _num(get_sensor_value(sens) if sens else 0.0, 0.0)
            eff   = max(tarif - fee_up, 0.0)
        else:
            eff = 0.0
        return f"Currently assumed PV-Costs: {eff:.4f} €/kWh"

    # FX-Info
    @app.callback(
        Output("set-fx-read","children"),
        Input("set-btc-currency","value"),
    )
    def _fx_info(cur):
        if (cur or "EUR").upper() == "USD":
            fx = usd_to_eur_rate()
            return f"USD→EUR: {fx:.4f}"
        return ""

    # Settings speichern
    @app.callback(
        Output("set-status","children"),
        Input("set-save","n_clicks"),
        State("set-pv-policy","value"),
        State("set-feedin-mode","value"),
        State("set-feedin-value","value"),
        State("set-feedin-sensor","value"),
        State("set-btc-currency","value"),
        State("set-reward","value"),
        State("set-tax","value"),
        State("set-cooling-enabled", "value"),
        prevent_initial_call=True
    )
    def _save(n, policy, mode, val, sens, cur, reward, tax, cool_enabled_val):
        if not n:
            return ""
        set_set(
            pv_cost_policy=(policy or "zero"),
            feedin_price_mode=(mode or "fixed"),
            feedin_price_value=_num(val, 0.0),
            feedin_price_sensor=(sens or ""),
            btc_price_currency=(cur or "EUR"),
            block_reward_btc=_num(reward, 3.125),
            sell_tax_percent=_num(tax, 0.0),
            cooling_feature_enabled=bool(cool_enabled_val and "on" in cool_enabled_val),
        )
        return "Saved."

    # -------- 1) Render bei Tab-Wechsel -> immer aus Persistenz mergen --------
    @app.callback(
        Output("prio-list", "children"),
        Input("active-tab", "data"),
    )
    def _prio_render_on_tab(active_tab):
        if active_tab != "settings":
            raise PreventUpdate
        children = _render_prio_children(order=None)
        return children

    # -------- 2) Schreiben + Rendern: Drop / Reset / Save --------
    @app.callback(
        Output("prio-list", "children", allow_duplicate=True),
        Output("prio-status", "children", allow_duplicate=True),
        Input("prio-dnd-wire", "value"),
        Input("prio-reset", "n_clicks"),
        Input("prio-save", "n_clicks"),
        prevent_initial_call=True
    )
    def _prio_write(val, n_reset, n_save):
        trig = callback_context.triggered_id

        if trig == "prio-reset":
            available = _prio_available_items()
            base_ids = [a["id"] for a in available]
            order = _prio_merge_with_stored(base_ids, available)
            _save_prio_ids(order)
            return _render_prio_children(order), "Reset to default."

        if trig == "prio-dnd-wire":
            try:
                ids = json.loads(val) if val else []
                if not isinstance(ids, list):
                    raise ValueError("wire not a list")
            except Exception:
                raise PreventUpdate
            _save_prio_ids(ids)
            return _render_prio_children(ids), "Priority saved!"

        if trig == "prio-save":
            # Schreibe den aktuell persistierten Stand erneut (falls Save separat gedrückt wird)
            current = _load_prio_ids()
            _save_prio_ids(current)
            return _render_prio_children(current), "Priority saved!"

        raise PreventUpdate
