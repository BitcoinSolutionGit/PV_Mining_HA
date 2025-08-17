# ui_pages/settings.py
import json
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from services.settings_store import get_var as set_get, set_vars as set_set
from services.electricity_store import get_var as elec_get
from services.ha_sensors import list_all_sensors, get_sensor_value
from services.forex import usd_to_eur_rate
from services.miners_store import list_miners

PRIO_KEY = "priority_order"
PRIO_KEY_JSON = "priority_order_json"

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

# ---------- helpers ----------
def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def _prio_available_items():
    items = []
    if bool(set_get("cooling_feature_enabled", False)):
        items.append({"id": "cooling", "label": "Cooling circuit", "color": PRIO_COLORS["cooling"]})
    try:
        for m in (list_miners() or []):
            items.append({"id": f"miner:{m['id']}", "label": m.get("name", "Miner"), "color": PRIO_COLORS["miners"]})
    except Exception:
        pass
    items += [
        {"id": "battery",   "label": "Battery",      "color": PRIO_COLORS["battery"]},
        {"id": "wallbox",   "label": "Wallbox",      "color": PRIO_COLORS["wallbox"]},
        {"id": "heater",    "label": "Water Heater", "color": PRIO_COLORS["heater"]},
        {"id": "house",     "label": "House load",   "color": PRIO_COLORS["load"]},
        {"id": "grid_feed", "label": "Grid feed-in", "color": PRIO_COLORS["grid_feed"]},
    ]
    # de-dupe
    seen, out = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"]); out.append(it)
    return out

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
    if isinstance(raw, list) and raw:
        print("[prio] load (yaml:list):", raw, flush=True)
        return raw
    raw_json = set_get(PRIO_KEY_JSON, "")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            val = json.loads(raw_json)
            if isinstance(val, list) and val:
                print("[prio] load (yaml:json):", val, flush=True)
                return val
        except Exception:
            pass
    print("[prio] load: EMPTY -> will fall back to merge/default", flush=True)
    return []

def _save_prio_ids(ids):
    set_set(**{PRIO_KEY: ids})
    set_set(**{PRIO_KEY_JSON: json.dumps(ids)})
    print("[prio] saved:", ids, flush=True)

def _prio_row(item, idx, length):
    # grid_feed bleibt unten -> Buttons deaktiviert
    is_grid = (item["id"] == "grid_feed")

    # Buttons rechts
    btn_up = html.Button(
        "↑",
        id={"type": "prio-move", "action": "up", "idx": idx},
        n_clicks=0,
        disabled=(idx == 0 or is_grid),
        className="custom-tab",
        style={"padding": "4px 10px", "minWidth": "42px"}
    )
    btn_down = html.Button(
        "↓",
        id={"type": "prio-move", "action": "down", "idx": idx},
        n_clicks=0,
        disabled=(idx == length - 1 or is_grid),
        className="custom-tab",
        style={"padding": "4px 10px", "minWidth": "42px", "marginLeft": "8px"}
    )
    right_controls = html.Div([btn_up, btn_down], style={"display": "flex", "alignItems": "center"})

    # Punkt + Label links
    dot = html.Span(
        "",
        style={
            "display": "inline-block",
            "width": "12px",
            "height": "12px",
            "borderRadius": "50%",
            "backgroundColor": item.get("color", "#ccc"),
            "marginRight": "10px",
            "verticalAlign": "middle",
        },
    )
    label = html.Span(
        item.get("label", ""),
        style={"fontSize": "16px", "fontWeight": "600"}  # <-- größere Schrift
    )
    left = html.Div([dot, label], style={"display": "flex", "alignItems": "center"})

    # gesamte Zeile: Rahmen, Padding, Buttons rechts
    return html.Div(
        [left, right_controls],
        className="prio-item",
        style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "space-between",
            "border": "1px solid #cfd4dc",
            "borderRadius": "10px",
            "padding": "10px 12px",
            "marginBottom": "8px",
            "backgroundColor": "#fff",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.05)",
        },
        **{"data-pid": item["id"]},
    )


# ---------- layout ----------
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
    eff_pv_cost = max((fi_val if mode == "fixed" else _num(get_sensor_value(fi_sens), 0.0)) - fee_up, 0.0) if policy == "feedin" else 0.0
    cooling_enabled = bool(set_get("cooling_feature_enabled", False))

    return html.Div([
        html.H2("Settings"),

        html.Fieldset([
            html.Legend("Cooling Circuit"),
            dcc.Checklist(
                id="set-cooling-enabled",
                options=[{"label": " Cooling circuit feature activ", "value": "on"}],
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
                options=[{"label": " PV = 0 €/kWh", "value": "zero"},
                         {"label": " PV = Feed-in tariff − network-fee (up)", "value": "feedin"}],
                value=policy, labelStyle={"display": "block", "marginBottom": "6px"}
            ),
            html.Div([
                html.Label("Source for Feed-in tariff"),
                dcc.RadioItems(
                    id="set-feedin-mode",
                    options=[{"label":" fixed Value","value":"fixed"}, {"label":" Sensor","value":"sensor"}],
                    value=mode, labelStyle={"display":"inline-block", "marginRight":"18px"}
                ),
            ], id="row-feed-mode", style={"marginTop":"6px", "display": ("block" if policy=="feedin" else "none")}),
            html.Div([
                html.Label("Feed-in tariff (€/kWh)"),
                dcc.Input(id="set-feedin-value", type="number", step=0.000001, value=fi_val, style={"width":"220px"}),
            ], id="row-feed-fixed", style={"marginTop":"6px", "display": ("block" if (policy=="feedin" and mode=="fixed") else "none")}),
            html.Div([
                html.Label("Feed-in tariff-Sensor"),
                dcc.Dropdown(id="set-feedin-sensor", options=sensors, value=fi_sens or None, placeholder="select Sensor..."),
            ], id="row-feed-sensor", style={"marginTop":"6px", "display": ("block" if (policy=="feedin" and mode=="sensor") else "none")}),
            html.Div(id="set-pv-effective", style={"marginTop":"8px", "fontWeight":"bold", "opacity":0.9},
                     children=f"Currently assumed PV-Costs: {eff_pv_cost:.4f} €/kWh"),
        ], style={"border":"1px solid #ccc", "borderRadius":"8px", "padding":"10px", "marginBottom":"14px"}),

        html.Fieldset([
            html.Legend("Bitcoin-economics"),
            html.Div([
                html.Label("BTC-Price-Currency"),
                dcc.Dropdown(id="set-btc-currency",
                    options=[{"label":"EUR","value":"EUR"}, {"label":"USD","value":"USD"}],
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
        html.P("Use ↑/↓ to reorder (top = highest priority). Grid feed-in is always last."),

        # Liste + Status
        html.Div(id="prio-list", className="prio-list"),
        html.Span(id="prio-status", style={"marginLeft":"6px","color":"green"}),
    ])

# ---------- callbacks ----------
def register_callbacks(app):
    # Sichtbarkeit PV-Unterfelder
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

    # Live PV-Kostenanzeige
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
        State("set-cooling-enabled","value"),
        prevent_initial_call=True
    )
    def _save(n, policy, mode, val, sens, cur, reward, tax, cool_enabled_val):
        if not n: return ""
        set_set(
            pv_cost_policy=(policy or "zero"),
            feedin_price_mode=(mode or "fixed"),
            feedin_price_value=_num(val, 0.0),
            feedin_price_sensor=(sens or ""),
            btc_price_currency=(cur or "EUR"),
            block_reward_btc=_num(reward, 3.125),
            sell_tax_percent=_num(tax, 0.0),
            cooling_feature_enabled=bool(cool_enabled_val and "on" in (cool_enabled_val or [])),
        )
        return "Saved."

    # Beim Öffnen des Settings-Tabs: Store hydratisieren (falls leer)
    @app.callback(
        Output("prio-order", "data", allow_duplicate=True),
        Input("active-tab", "data"),
        State("prio-order", "data"),
        prevent_initial_call=True
    )
    def _hydrate_on_settings_tab(active_tab, cur_store):
        if active_tab != "settings":
            raise PreventUpdate
        if cur_store:
            raise PreventUpdate
        available = _prio_available_items()
        order = _prio_merge_with_stored(_load_prio_ids(), available)
        print("[prio] hydrate ->", order, flush=True)
        return order

    # Up/Down -> Auto-Save
    @app.callback(
        Output("prio-order", "data"),
        Output("prio-status", "children"),
        Input({"type": "prio-move", "action": ALL, "idx": ALL}, "n_clicks"),
        State("prio-order", "data"),
        prevent_initial_call=True
    )
    def _prio_move(_clicks, current):
        trig = dash.callback_context.triggered_id
        if not isinstance(trig, dict) or trig.get("type") != "prio-move":
            raise PreventUpdate

        action = trig.get("action")
        try:
            idx = int(trig.get("idx"))
        except Exception:
            raise PreventUpdate

        available = _prio_available_items()
        if not current:
            current = _prio_merge_with_stored(_load_prio_ids(), available)

        order = list(current)
        if idx < 0 or idx >= len(order):
            raise PreventUpdate

        # grid_feed bleibt immer unten
        if order[idx] == "grid_feed":
            raise PreventUpdate

        if action == "up" and idx > 0:
            order[idx-1], order[idx] = order[idx], order[idx-1]
        elif action == "down" and idx < len(order) - 1:
            order[idx+1], order[idx] = order[idx], order[idx+1]
        else:
            raise PreventUpdate

        # grid_feed ans Ende schieben (falls vorhanden)
        if "grid_feed" in order:
            order = [x for x in order if x != "grid_feed"] + ["grid_feed"]

        _save_prio_ids(order)
        print(f"[prio] move {action}@{idx} -> {order}", flush=True)
        return order, "Saved."

    # Rendering der Liste
    @app.callback(
        Output("prio-list", "children"),
        Input("prio-order", "data")
    )
    def _prio_render(order):
        available = _prio_available_items()
        if not order:
            order = _prio_merge_with_stored(_load_prio_ids(), available)

        by_id = {a["id"]: a for a in available}
        seq = [by_id[i] for i in order if i in by_id]
        # neue Items hinten anfügen (außer grid_feed)
        for a in available:
            if a["id"] not in order and a["id"] != "grid_feed":
                seq.append(a)
        # grid_feed sicherstellen
        if "grid_feed" in by_id and all(x["id"] != "grid_feed" for x in seq):
            seq.append(by_id["grid_feed"])

        rows = []
        n = len(seq)
        for i, it in enumerate(seq):
            rows.append(_prio_row(it, i, n))
        print("[prio] render -> order:", [x["id"] for x in seq], flush=True)
        return rows
