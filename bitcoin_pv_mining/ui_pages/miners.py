import math
import dash
import os
from dash import no_update
from dash import html, dcc, callback_context
from dash.dependencies import Input, Output, State, MATCH, ALL

from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour
from services.miners_store import list_miners, add_miner, update_miner, delete_miner
from services.settings_store import get_var as set_get, set_vars as set_set
from services.electricity_store import current_price as elec_price, get_var as elec_get, currency_symbol
from services.license import is_premium_enabled
from services.utils import load_yaml
from services.ha_sensors import get_sensor_value
from services.cooling_store import get_cooling, set_cooling
from services.ha_entities import list_actions


CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")

def _dash_resolve(kind: str) -> str:
    def _mget(path, key):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(key) or "").strip()
    return _mget(SENS_OVR, kind) or _mget(SENS_DEF, kind)

# ---------- helpers ----------
def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

def _clamp01(x):
    x = _num(x, 0.0)
    return 1.0 if x > 1.0 else (0.0 if x < 0.0 else x)

def sats_per_th_per_hour(block_reward_btc: float, network_hashrate_ths: float) -> float:
    # 6 Blöcke/h * Reward / Netzhashrate
    if network_hashrate_ths <= 0: return 0.0
    return block_reward_btc * 6.0 * 1e8 / network_hashrate_ths

def _dot(color):
    return html.Span("", style={"display":"inline-block","width":"10px","height":"10px","borderRadius":"50%","backgroundColor":color,"marginRight":"8px","verticalAlign":"middle"})

def _money(v):
    try:
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "–"

def _pv_cost_per_kwh():
    # policy: zero | feedin
    policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
    if policy != "feedin":
        return 0.0
    mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    if mode == "sensor":
        sens = set_get("feedin_price_sensor", "") or ""
        tarif = _num(get_sensor_value(sens) if sens else 0.0, 0.0)
    else:
        tarif = _num(set_get("feedin_price_value", 0.0), 0.0)
    return max(tarif - fee_up, 0.0)  # nicht negativ

def _cool_card(c: dict, sym: str, ha_actions: list[dict]):
    return html.Div([
        html.Div([ html.Strong(c.get("name","Cooling circuit")) ],
                 style={"display":"flex","justifyContent":"space-between","alignItems":"center","marginBottom":"6px"}),

        # Erste Zeile: Enabled (read only), Mode, Power (on/off)
        html.Div([
            html.Div([ html.Label("Enabled"),
                dcc.Checklist(
                    id="cool-enabled",
                    options=[{"label":" on","value":"on","disabled":True}],
                    value=["on"],
                    inputStyle={"cursor": "not-allowed"},
                    style={"opacity": 0.7},
                    persistence=True, persistence_type="memory"
                )
            ], style={"opacity": 0.7, "pointerEvents": "none"}),

            html.Div([ html.Label("Mode (auto)"),
                dcc.Checklist(
                    id="cool-mode",
                    options=[{"label":" on","value":"auto"}],
                    value=(["auto"] if c.get("mode","manual")=="auto" else []),
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex":"1","marginLeft":"10px"}),

            html.Div([ html.Label("Power (on/off)"),
                dcc.Checklist(
                    id="cool-on",
                    options=[{"label":" on","value":"on"}],
                    value=(["on"] if c.get("on", False) else []),
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","gap":"10px","marginTop":"6px","flexWrap":"wrap"}),

        # Zweite Zeile: Aktionen (Script/Switch)
        html.Div([
            html.Div([
                html.Label("Power ON action"),
                dcc.Dropdown(
                    id="cool-act-on",
                    options=ha_actions,
                    value=c.get("action_on_entity", "") or None,
                    placeholder="Select script or switch…",
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex": "1", "minWidth":"240px"}),

            html.Div([
                html.Label("Power OFF action"),
                dcc.Dropdown(
                    id="cool-act-off",
                    options=ha_actions,
                    value=c.get("action_off_entity", "") or None,
                    placeholder="Select script or switch…",
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex": "1", "minWidth":"240px","marginLeft": "10px"}),
        ], style={"display":"flex","gap":"10px","marginTop":"8px","flexWrap":"wrap"}),

        # Leistung
        html.Div([
            html.Div([ html.Label("Cooling power (kW)"),
                dcc.Input(id="cool-pwr", type="number", step=0.01,
                          value=float(c.get("power_kw",0.0) or 0.0),
                          style={"width":"160px"},
                          persistence=True, persistence_type="memory") ], style={"flex":"1"}),
        ], style={"display":"flex","gap":"10px","marginTop":"8px"}),

        html.Div(id="cool-kpi", style={"marginTop":"8px", "fontWeight":"bold"}),

        html.Button("Save", id="cool-save", className="custom-tab", style={"marginTop":"8px"}),
        html.Span("  (Cooling must run before any miner switches on)", style={"marginLeft":"8px","opacity":0.7}),

        html.Div(id="cool-lock-note", style={"marginTop": "6px", "opacity": 0.75})
    ], style={"border":"2px solid #888","borderRadius":"8px","padding":"10px","background":"#fafafa"})


def _miner_card_style(idx: int) -> dict:
    base = {"borderRadius": "8px", "padding": "10px", "background": "#fafafa"}
    if idx == 0:
        # Miner 1: grauer Rahmen wie Cooling
        return {**base, "border": "2px solid #888"}
    # Miner 2..n: grüner Premium-Rahmen
    return {**base, "border": "2px solid #27ae60"}

# ---------- layout ----------
def layout():
    prem = is_premium_enabled()
    miners = list_miners()
    if not miners:
        # Ersten Miner automatisch anlegen (free)
        add_miner("Miner 1")
        miners = list_miners()

    # globale settings initial
    btc_eur = _num(set_get("btc_price_eur", 0.0))
    net_ths = _num(set_get("network_hashrate_ths", 0.0))
    reward  = _num(set_get("block_reward_btc", 3.125))
    tax_pct = _num(set_get("sell_tax_percent", 0.0))
    sat_th_h = sats_per_th_per_hour(reward, net_ths)

    sym = currency_symbol()
    ha_actions = list_actions()

    cooling_feature = bool(set_get("cooling_feature_enabled", False))
    cooling = get_cooling() if cooling_feature else None

    return html.Div([
        html.H2("Miners"),

        # --- Global economics box ---
        html.Details([
            html.Summary("Global mining economics"),
            html.Div([
                html.Label("BTC price"),
                dcc.Input(id="miners-btc-eur", type="number", step=0.01, value=btc_eur, style={"width":"160px"}),
                html.Span(" €"),

                html.Span("   "),
                html.Label("Network hashrate (TH/s)", style={"marginLeft":"16px"}),
                dcc.Input(id="miners-net-ths", type="number", step=1e6, value=net_ths, style={"width":"180px"}),

                html.Span("   "),
                html.Label("Block reward (BTC)", style={"marginLeft":"16px"}),
                dcc.Input(id="miners-reward-btc", type="number", step=0.0001, value=reward, style={"width":"120px"}),

                html.Span("   "),
                html.Label("Sell tax % (KESt)", style={"marginLeft":"16px"}),
                dcc.Input(id="miners-tax", type="number", step=0.1, value=tax_pct, style={"width":"100px"}),

                html.Button("Save", id="miners-settings-save", className="custom-tab", style={"marginLeft":"16px"}),
                html.Span(f"   SAT/TH/h: {sat_th_h:,.2f}".replace(",", "X").replace(".", ",").replace("X","."), id="miners-satthh", style={"marginLeft":"16px","fontWeight":"bold"})
            ], style={"display":"flex","alignItems":"center","flexWrap":"wrap","gap":"8px","marginTop":"8px"}),
            html.Div(id="miners-settings-status", style={"color":"green","marginTop":"6px"})
        ], open=False),

        html.Div([
            html.Button("Add miner", id="miners-add", className="custom-tab"),
            html.Span(id="miners-add-status", style={"marginLeft":"10px","color":"#e74c3c"})
        ], style={"margin":"10px 0"}),

        (_cool_card(cooling, sym, ha_actions) if cooling_feature else html.Div()),
        (html.Hr() if cooling_feature else html.Div()),

        dcc.Store(id="miners-data"),  # hält aktuelle Liste
        dcc.Store(id="miners-delete-target"),
        dcc.ConfirmDialog(id="miners-confirm", message="Diesen Miner wirklich löschen?"),

        html.Div(id="miners-cards",
                 style={"display": "flex", "flexDirection": "column", "gap": "16px"}),

        # EINMALIGER Mount-Trigger zum Laden der Miner-Liste
        dcc.Interval(id="miners-once", interval=1, n_intervals=0, max_intervals=1),

        # Nur für Live-KPIs (NICHT mehr zum Neu-Laden der Daten verwenden)
        dcc.Interval(id="miners-refresh", interval=10_000, n_intervals=0)
    ])

# ---------- render helpers ----------
def _miner_card(m: dict, idx: int, premium_on: bool, sym: str, ha_actions: list[dict]):
    mid = m["id"]
    is_free = (idx == 0)  # erster Miner gratis
    frame_style = {} if is_free else {"border":"2px solid #27ae60","borderRadius":"8px","padding":"10px"}

    return html.Div([
        html.Div([
            html.Strong(m.get("name","")),
            html.Button("🗑", id={"type":"m-del", "mid":mid}, n_clicks=0, title="Löschen", style={"float":"right"})
        ], style={"display":"flex","justifyContent":"space-between","alignItems":"center","marginBottom":"6px"}),

        html.Label("Name"),
        dcc.Input(id={"type": "m-name", "mid": mid}, type="text",
                  value=m.get("name", ""), style={"width": "100%"},
                  persistence=True, persistence_type="memory"),

        html.Div([
            html.Div([
                html.Label("Enabled"),
                dcc.Checklist(id={"type": "m-enabled", "mid": mid}, options=[{"label": " on", "value": "on"}],
                              value=(["on"] if m.get("enabled", True) else []),
                              persistence=True, persistence_type="memory"),
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Mode (auto)"),
                dcc.Checklist(id={"type": "m-mode", "mid": mid}, options=[{"label": " on", "value": "auto"}],
                              value=(["auto"] if m.get("mode", "manual") == "auto" else []),
                              persistence=True, persistence_type="memory"),
            ], style={"flex":"1","marginLeft":"10px"}),
            html.Div([
                html.Label("Power (on/off)"),
                dcc.Checklist(id={"type": "m-on", "mid": mid}, options=[{"label": " on", "value": "on"}],
                              value=(["on"] if m.get("on", False) else []),
                              persistence=True, persistence_type="memory"),
            ], style={"flex":"1","marginLeft":"10px"}),
            html.Div([
                html.Label("Cooling required"),
                dcc.Checklist(
                    id={"type": "m-reqcool", "mid": mid},
                    options=[{"label": " on", "value": "on"}],
                    value=(["on"] if m.get("require_cooling", False) else []),
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex": "1", "marginLeft": "10px"}),
        ], style={"display":"flex","gap":"10px","marginTop":"6px"}),

        html.Div([
            html.Div([
                html.Label("Hashrate (TH/s)"),
                dcc.Input(id={"type": "m-hash", "mid": mid}, type="number", step=0.01,
                          value=_num(m.get("hashrate_ths", 0)), style={"width": "100%"},
                          persistence=True, persistence_type="memory"),
            ], style={"flex":"1"}),
            html.Div([
                html.Label("Power (kW)"),
                dcc.Input(id={"type": "m-pwr", "mid": mid}, type="number", step=0.01,
                          value=_num(m.get("power_kw", 0)), style={"width": "100%"},
                          persistence=True, persistence_type="memory"),
            ], style={"flex":"1","marginLeft":"10px"}),
        ], style={"display":"flex","gap":"10px","marginTop":"8px"}),

        html.Div([
            html.Div([
                html.Label("Power ON action"),
                dcc.Dropdown(
                    id={"type": "m-act-on", "mid": m["id"]},
                    options=ha_actions,
                    value=m.get("action_on_entity", "") or None,
                    placeholder="Select script or switch…",
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex": "1"}),
            html.Div([
                html.Label("Power OFF action"),
                dcc.Dropdown(
                    id={"type": "m-act-off", "mid": m["id"]},
                    options=ha_actions,
                    value=m.get("action_off_entity", "") or None,
                    placeholder="Select script or switch…",
                    persistence=True, persistence_type="memory"
                )
            ], style={"flex": "1", "marginLeft": "10px"}),
        ], style={"display": "flex", "gap": "10px", "marginTop": "8px"}),

        html.Hr(),

        # live KPIs
        html.Div(id={"type":"m-kpi-satthh","mid":mid}, style={"fontWeight":"bold"}),
        html.Div(id={"type":"m-kpi-eurh","mid":mid}),
        html.Div(id={"type":"m-kpi-profit","mid":mid}, style={"marginTop":"2px"}),

        html.Button("Save", id={"type":"m-save","mid":mid}, className="custom-tab", style={"marginTop":"8px"})
    ], style=_miner_card_style(idx))

# ---------- callbacks ----------
def register_callbacks(app):
    sym = currency_symbol()

    # 0) initial miners-data füllen
    @app.callback(
        Output("miners-data", "data"),
        Input("miners-once", "n_intervals"),
        prevent_initial_call=False
    )
    def _load_once(_n):
        return list_miners()

    # 1) render cards
    @app.callback(
        Output("miners-cards", "children"),
        Input("miners-data", "data")
    )
    def _render(miners):
        prem = is_premium_enabled()
        miners = miners or []
        try:
            ha_actions = list_actions()  # <- HIER holen (scripts + switches)
        except Exception:
            ha_actions = []
        return [_miner_card(m, i, prem, sym, ha_actions) for i, m in enumerate(miners)]

    # 2) Global settings speichern
    @app.callback(
        Output("miners-settings-status","children"),
        Output("miners-satthh","children"),
        Input("miners-settings-save","n_clicks"),
        State("miners-btc-eur","value"),
        State("miners-net-ths","value"),
        State("miners-reward-btc","value"),
        State("miners-tax","value"),
        prevent_initial_call=True
    )
    def _save_settings(n, btc_eur, net_ths, reward, tax):
        if not n: return "", dash.no_update
        set_set(btc_price_eur=_num(btc_eur,0.0), network_hashrate_ths=_num(net_ths,0.0),
                block_reward_btc=_num(reward,3.125), sell_tax_percent=_num(tax,0.0))
        sat = sats_per_th_per_hour(_num(reward,3.125), _num(net_ths,0.0))
        txt = f"SAT/TH/h: {sat:,.2f}".replace(",", "X").replace(".", ",").replace("X",".")
        return "Settings saved!", txt

    # 3) Add miner (Premium-Gate: nur Miner 1 frei)
    @app.callback(
        Output("miners-add-status","children"),
        Output("miners-data","data", allow_duplicate=True),
        Input("miners-add","n_clicks"),
        State("miners-data","data"),
        prevent_initial_call=True
    )
    def _add(n, cur):
        if not n: return "", dash.no_update
        prem = is_premium_enabled()
        cur = cur or []
        if not prem and len(cur) >= 1:
            return "Premium required for additional miners.", dash.no_update
        add_miner()
        return "", list_miners()

    # 4) Delete flow: Button -> ConfirmDialog auf
    @app.callback(
        Output("miners-confirm", "displayed"),
        Output("miners-delete-target", "data"),
        Input({"type": "m-del", "mid": ALL}, "n_clicks"),
        prevent_initial_call=True
    )
    def _ask_delete(nclicks_list):
        # 1) Nichts geklickt -> nichts tun
        if not nclicks_list or all((n or 0) == 0 for n in nclicks_list):
            raise dash.exceptions.PreventUpdate

        # 2) Sicher den Trigger identifizieren (ohne eval)
        trg = dash.callback_context.triggered_id
        if not isinstance(trg, dict) or trg.get("type") != "m-del":
            raise dash.exceptions.PreventUpdate

        mid = trg.get("mid")
        if not mid:
            raise dash.exceptions.PreventUpdate

        # 3) Dialog öffnen + Ziel-ID setzen
        return True, mid

    # 5) Confirm -> löschen
    @app.callback(
        Output("miners-data","data", allow_duplicate=True),
        Input("miners-confirm","submit_n_clicks"),
        State("miners-delete-target","data"),
        prevent_initial_call=True
    )
    def _do_delete(ok, mid):
        if not ok or not mid: raise dash.exceptions.PreventUpdate
        delete_miner(mid)
        return list_miners()

    #6 und #7 zusammengeführt
    @app.callback(
        Output({"type": "m-mode", "mid": MATCH}, "options"),
        Output({"type": "m-mode", "mid": MATCH}, "value"),
        Output({"type": "m-on", "mid": MATCH}, "disabled"),
        Output({"type": "m-on", "mid": MATCH}, "style"),
        Output({"type": "m-name", "mid": MATCH}, "disabled"),
        Output({"type": "m-hash", "mid": MATCH}, "disabled"),
        Output({"type": "m-pwr", "mid": MATCH}, "disabled"),
        Output({"type": "m-act-on", "mid": MATCH}, "disabled"),
        Output({"type": "m-act-off", "mid": MATCH}, "disabled"),
        Input({"type": "m-enabled", "mid": MATCH}, "value"),
        Input({"type": "m-mode", "mid": MATCH}, "value"),
        Input({"type": "m-reqcool", "mid": MATCH}, "value"),
        Input("cool-enabled", "value"),  # existiert nur, wenn Feature aktiv (ok dank suppress_callback_exceptions)
        Input("cool-on", "value"),
    )
    def _apply_enable_mode_with_cooling(enabled_val, mode_val, reqcool_val, cool_en_val, cool_on_val):
        enabled = bool(enabled_val and "on" in enabled_val)
        mode_auto = bool(mode_val and "auto" in mode_val)
        require_cooling = bool(reqcool_val and "on" in reqcool_val)

        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        cooling_enabled = bool(cool_en_val and "on" in cool_en_val) if cooling_feature else False
        cooling_on = bool(cool_on_val and "on" in cool_on_val) if cooling_feature else False

        lock_on = (not enabled) or mode_auto or (
                    cooling_feature and require_cooling and (not cooling_enabled or not cooling_on))
        on_style = {"opacity": 0.6, "pointerEvents": "none"} if lock_on else {}

        inputs_disabled = not enabled
        opts = [{"label": " on", "value": "auto"}]
        val = ["auto"] if mode_auto else []
        return opts, val, lock_on, on_style, inputs_disabled, inputs_disabled, inputs_disabled, inputs_disabled, inputs_disabled

    # 8) Save pro Miner (ALL statt MATCH)


    @app.callback(
        Output("miners-data", "data", allow_duplicate=True),
        Input({"type": "m-save", "mid": ALL}, "n_clicks"),
        State({"type": "m-save", "mid": ALL}, "id"),
        State({"type": "m-name", "mid": ALL}, "value"),
        State({"type": "m-enabled", "mid": ALL}, "value"),
        State({"type": "m-mode", "mid": ALL}, "value"),
        State({"type": "m-on", "mid": ALL}, "value"),
        State({"type": "m-hash", "mid": ALL}, "value"),
        State({"type": "m-pwr", "mid": ALL}, "value"),
        State({"type": "m-reqcool", "mid": ALL}, "value"),
        State({"type": "m-act-on", "mid": ALL}, "value"),
        State({"type": "m-act-off", "mid": ALL}, "value"),
        prevent_initial_call=True
    )
    def _save_miner(nclicks_list, save_ids, names, enabled_vals, mode_vals, on_vals, ths_vals, pkw_vals, reqcool_vals, act_on_vals, act_off_vals):
        # Welcher Save-Button hat ausgelöst?
        trg = callback_context.triggered_id
        if not trg:
            raise dash.exceptions.PreventUpdate
        mid = trg.get("mid")  # z.B. "m_abcd1234"

        # Index des geklickten Buttons in den ALL-Listen finden
        try:
            idx = next(i for i, sid in enumerate(save_ids) if sid.get("mid") == mid)
        except StopIteration:
            raise dash.exceptions.PreventUpdate

        # Werte sauber herausziehen
        name = names[idx] if idx < len(names) else ""
        enable = bool(enabled_vals[idx] and "on" in enabled_vals[idx]) if idx < len(enabled_vals) else False
        mode = "auto" if (idx < len(mode_vals) and mode_vals[idx] and "auto" in mode_vals[idx]) else "manual"
        on = bool(on_vals[idx] and "on" in on_vals[idx]) if idx < len(on_vals) else False
        reqc = bool(reqcool_vals[idx] and "on" in reqcool_vals[idx]) if idx < len(reqcool_vals) else False
        act_on = (act_on_vals[idx] if idx < len(act_on_vals) else None) or ""
        act_off = (act_off_vals[idx] if idx < len(act_off_vals) else None) or ""

        def _num(x, d=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return d

        ths = _num(ths_vals[idx] if idx < len(ths_vals) else 0.0, 0.0)
        pkw = _num(pkw_vals[idx] if idx < len(pkw_vals) else 0.0, 0.0)

        # Speichern
        update_miner(mid,
                     name=name or "",
                     enabled=enable,
                     mode=mode,
                     on=on,
                     hashrate_ths=ths,
                     power_kw=pkw,
                     require_cooling=reqc,
                     action_on_entity=act_on,
                     action_off_entity=act_off)

        # Liste neu laden
        return list_miners()

    # 9) KPIs je Miner live berechnen (alle 10s + bei Eingaben)
    @app.callback(
        Output({"type": "m-kpi-satthh", "mid": MATCH}, "children"),
        Output({"type": "m-kpi-eurh", "mid": MATCH}, "children"),
        Output({"type": "m-kpi-profit", "mid": MATCH}, "children"),
        Input("miners-refresh", "n_intervals"),
        Input({"type": "m-hash", "mid": MATCH}, "value"),
        Input({"type": "m-pwr", "mid": MATCH}, "value"),
        State({"type": "m-enabled", "mid": MATCH}, "value"),
        State({"type": "m-mode", "mid": MATCH}, "value"),
        State({"type": "m-on", "mid": MATCH}, "value"),
        State({"type": "m-reqcool", "mid": MATCH}, "value"),
    )
    def _recalc(_tick, ths, pkw, enabled_val, mode_val, on_val, reqcool_val):
        def _num(x, d=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return d

        # --- Live BTC & Netzwerk ---
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

        sat_th_h = sats_per_th_per_hour(reward, net_ths)

        ths = _num(ths, 0.0)
        pkw = _num(pkw, 0.0)

        # Einnahmen/h
        sats_per_h = sat_th_h * ths
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
        revenue_eur_h = sats_per_h * eur_per_sat
        after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

        # --- Inkrementeller PV/Grid-Mix für diesen Miner ---
        pv_id = _dash_resolve("pv_production")
        grid_id = _dash_resolve("grid_consumption")
        feed_id = _dash_resolve("grid_feed_in")

        pv_val = _num(get_sensor_value(pv_id), 0.0)
        grid_val = _num(get_sensor_value(grid_id), 0.0)
        feed_val = max(_num(get_sensor_value(feed_id), 0.0), 0.0)  # >=0

        base = elec_price() or 0.0
        fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)
        pv_cost = _pv_cost_per_kwh()

        # Cooling-Setup
        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        require_cooling = bool(reqcool_val and "on" in reqcool_val)
        c = get_cooling() if cooling_feature else {}
        cooling_kw_cfg = float((c or {}).get("power_kw") or 0.0)
        cooling_is_on = bool((c or {}).get("on"))

        # Zusätzliche Last ΔP: Miner + ggf. Cooling, falls dieser Miner Cooling neu starten würde
        delta_kw = pkw + (cooling_kw_cfg if (cooling_feature and require_cooling and not cooling_is_on) else 0.0)

        if delta_kw > 0.0:
            pv_share_add = max(min(feed_val / delta_kw, 1.0), 0.0)
        else:
            pv_share_add = 0.0
        grid_share_add = 1.0 - pv_share_add

        blended_eur_per_kwh = pv_share_add * pv_cost + grid_share_add * (base + fee_down)

        # Cooling-Kostenanteil fair teilen (aktive cooling-Miner + dieser Miner)
        cool_share = 0.0
        if cooling_feature and require_cooling and cooling_kw_cfg > 0.0:
            active = [m for m in list_miners() if m.get("enabled") and m.get("on") and m.get("require_cooling")]
            n_future = len(active) + 1  # inkl. diesem Miner
            cool_share = (cooling_kw_cfg * blended_eur_per_kwh) / max(n_future, 1)

        # Kosten/h
        cost_eur_h = pkw * blended_eur_per_kwh
        total_cost_h = cost_eur_h + cool_share

        profit = after_tax - total_cost_h
        profitable = profit > 0.0

        # ---------- Ausgabe ----------
        def _fmt_int(x):
            try:
                return f"{x:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except Exception:
                return "0"

        sat_txt = f"SAT/h: {_fmt_int(sats_per_h)}"

        parts = [
            f"Revenue: {_money(after_tax)} {currency_symbol()}/h",
            html.Span("|", style={"padding": "0 14px", "opacity": 0.7}),
            f"Cost at PV {pv_share_add * 100:.0f}% / Grid {grid_share_add * 100:.0f}%: "
            f"{_money(cost_eur_h)} {currency_symbol()}/h",
        ]
        if cool_share > 0.0:
            parts += [
                html.Span("|", style={"padding": "0 14px", "opacity": 0.7}),
                f"(+ Cooling share: {_money(cool_share)} {currency_symbol()}/h)",
            ]
        parts += [
            html.Span("|", style={"padding": "0 14px", "opacity": 0.7}),
            f"Δ = {_money(profit)} {currency_symbol()}/h",
        ]
        eur_txt = html.Span(parts)

        # Break-even Gridpreis bei aktuellem PV-Mix
        be_line = ""
        if pkw > 0.0:
            # "Äquivalente" kW inkl. anteiligem Cooling, wenn dieser Miner Cooling braucht
            if cooling_feature and require_cooling and cooling_kw_cfg > 0.0:
                active = [m for m in list_miners() if m.get("enabled") and m.get("on") and m.get("require_cooling")]
                n_future = len(active) + 1
                equiv_kw = pkw + (cooling_kw_cfg / max(n_future, 1))
            else:
                equiv_kw = pkw

            if equiv_kw > 0.0:
                blended_be = after_tax / equiv_kw  # benötigter €/kWh
                if grid_share_add <= 1e-6:
                    be_line = "Break-even grid price: n/a (PV fully covers incremental load)"
                else:
                    base_be = (blended_be - pv_share_add * pv_cost) / grid_share_add - fee_down
                    base_be = max(base_be, 0.0)
                    be_line = f"Break-even grid price at current PV mix: {_money(base_be)} €/kWh"

        prof_txt = html.Div([
            html.Span([_dot("#27ae60" if profitable else "#e74c3c"),
                       "profitable" if profitable else "not profitable"]),
            html.Br(),
            html.Span(be_line, style={"opacity": 0.8})
        ])

        return sat_txt, eur_txt, prof_txt

    # 10) KPI-Renderer + Cooling-Callbacks
    from dash import no_update
    from services.miners_store import list_miners

    @app.callback(
        Output("cool-on", "disabled"),
        Output("cool-on", "style"),
        Output("cool-on", "value"),  # ggf. automatisch auf ["on"] zurücksetzen
        Output("cool-lock-note", "children"),
        Input("cool-mode", "value"),
        Input("miners-refresh", "n_intervals"),  # regelmäßig prüfen
        State("cool-on", "value"),
    )
    def _cool_disable(mode_val, _tick, cur_on):
        mode_auto = bool(mode_val and "auto" in mode_val)

        # Läuft irgendein Miner, der Cooling benötigt?
        active_required = any(
            m.get("enabled") and m.get("on") and m.get("require_cooling")
            for m in list_miners()
        )

        locked = mode_auto or active_required
        style = {"opacity": 0.6, "pointerEvents": "none"} if locked else {}

        # Wenn gesperrt und aktuell "off", sofort visuell und logisch auf "on" zurücksetzen
        value_out = ["on"] if (locked and (cur_on != ["on"])) else no_update

        note = ""
        if active_required:
            note = "Cooling cannot be turned off while miners with 'Cooling required' are running."
        elif mode_auto:
            note = "Cooling is in Auto mode and cannot be switched off manually here."

        return locked, style, value_out, note

    @app.callback(
        Output("cool-kpi", "children"),
        Input("cool-save", "n_clicks"),
        State("cool-mode", "value"),
        State("cool-on", "value"),
        State("cool-pwr", "value"),
        State("cool-act-on", "value"),
        State("cool-act-off", "value"),
        prevent_initial_call=True
    )
    def _cool_save(n, mode_val, on_val, pkw, act_on, act_off):
        if not n:
            raise dash.exceptions.PreventUpdate

        mode_auto = bool(mode_val and "auto" in mode_val)

        # Läuft irgendein cooling-pflichtiger Miner?
        active_required = any(
            m.get("enabled") and m.get("on") and m.get("require_cooling")
            for m in list_miners()
        )

        # Wenn gesperrt -> ON erzwingen, egal was im UI steht
        force_on = mode_auto or active_required

        set_cooling(
            enabled=True,  # Enabled ist bei dir ohnehin read-only immer ON
            mode=("auto" if mode_auto else "manual"),
            on=(True if force_on else bool(on_val and "on" in on_val)),
            power_kw=float(pkw or 0.0),
            action_on_entity=(act_on or ""),
            action_off_entity=(act_off or "")
        )

        return _cool_kpi_render(float(pkw or 0.0))

    @app.callback(
        Output("cool-kpi", "children", allow_duplicate=True),
        Input("miners-refresh", "n_intervals"),
        State("cool-pwr","value"),
        prevent_initial_call=True
    )
    def _cool_tick(_n, pkw):
        return _cool_kpi_render(float(pkw or 0.0))

    def _cool_kpi_render(power_kw: float):
        def _f(x):
            try: return float(x)
            except: return 0.0
        pv_id   = _dash_resolve("pv_production")
        grid_id = _dash_resolve("grid_consumption")
        pv   = _f(get_sensor_value(pv_id))
        grid = _f(get_sensor_value(grid_id))
        inflow = max(pv + grid, 0.0)
        if inflow > 0:
            pv_share   = max(min(pv/inflow, 1.0), 0.0)
            grid_share = max(min(grid/inflow, 1.0), 0.0)
        else:
            pv_share, grid_share = 0.0, 1.0

        from services.electricity_store import current_price as elec_price, get_var as elec_get, currency_symbol
        base = elec_price() or 0.0
        def _num(x, d=0.0):
            try: return float(x)
            except: return d
        fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)

        from services.settings_store import get_var as set_get
        fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
        # PV-Kosten nach Policy
        if (set_get("pv_cost_policy","zero") or "zero").lower() == "feedin":
            mode = (set_get("feedin_price_mode","fixed") or "fixed").lower()
            if mode == "sensor":
                sens = set_get("feedin_price_sensor","") or ""
                tarif = _num(get_sensor_value(sens) if sens else 0.0, 0.0)
            else:
                tarif = _num(set_get("feedin_price_value",0.0),0.0)
            if 3.0 <= tarif < 1000.0:  # ct/kWh → €/kWh
                tarif /= 100.0
            pv_cost = max(tarif - fee_up, 0.0)
        else:
            pv_cost = 0.0

        blended = pv_share * pv_cost + grid_share * (base + fee_down)
        cost = power_kw * blended
        cs = currency_symbol()
        return f"Cooling-Costs: {cost:.2f} {cs}/h  (Mix PV {pv_share*100:.0f}% / Grid {grid_share*100:.0f}%)"
