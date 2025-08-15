# ui_pages/settings.py
import os
from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash

from services.settings_store import get_var as set_get, set_vars as set_set
from services.electricity_store import get_var as elec_get
from services.ha_sensors import list_all_sensors, get_sensor_value
from services.forex import usd_to_eur_rate

CONFIG_DIR = "/config/pv_mining_addon"

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def layout():
    # initiale Settings
    policy   = (set_get("pv_cost_policy", "zero") or "zero").lower()
    mode     = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
    fi_val   = _num(set_get("feedin_price_value", 0.0), 0.0)
    fi_sens  = set_get("feedin_price_sensor", "") or ""
    currency = (set_get("btc_price_currency", "EUR") or "EUR").upper()
    reward   = _num(set_get("block_reward_btc", 3.125), 3.125)
    tax_pct  = _num(set_get("sell_tax_percent", 0.0), 0.0)

    sensors = [{"label": s, "value": s} for s in list_all_sensors()]

    # aktuelle effektive PV-Kosten jetzt (nur Anzeige)
    fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
    eff_pv_cost = max((fi_val if mode=="fixed" else _num(get_sensor_value(fi_sens), 0.0)) - fee_up, 0.0) if policy=="feedin" else 0.0

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
                        {"label":" Sensor",  "value":"sensor"},
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
                html.Label("Feed-in tariff-Sensor"),
                dcc.Dropdown(id="set-feedin-sensor", options=sensors, value=fi_sens or None, placeholder="select Sensor..."),
            ], id="row-feed-sensor", style={"marginTop":"6px", "display": ("block" if (policy=="feedin" and mode=="sensor") else "none")}),

            html.Div(id="set-pv-effective", style={"marginTop":"8px", "fontWeight":"bold", "opacity":0.9},
                     children=f"current assumed PV-costs: {eff_pv_cost:.4f} €/kWh"),
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
    ])

def register_callbacks(app):
    # Sichtbarkeit der Feed-in Reihen steuern
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

    # Live-Anzeige effektive PV-Kosten
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

    # FX-Text (nur Info)
    @app.callback(
        Output("set-fx-read","children"),
        Input("set-btc-currency","value"),
    )
    def _fx_info(cur):
        if (cur or "EUR").upper() == "USD":
            fx = usd_to_eur_rate()
            return f"USD→EUR: {fx:.4f}"
        return ""

    # Save
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
        if not n: return ""
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
