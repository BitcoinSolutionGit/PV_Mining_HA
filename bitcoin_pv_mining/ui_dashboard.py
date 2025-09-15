import os
import yaml
import traceback
import plotly.graph_objects as go

from dash import html, dcc
from dash.dependencies import Input, Output

from services.ha_sensors import get_sensor_value
from services.utils import load_yaml
from services.battery_store import get_var as bat_get
from services.electricity_store import current_price, currency_symbol, get_var as elec_get
from services.heater_store import resolve_entity_id as heater_resolve_entity, get_var as heat_get_var
from services.miners_store import list_miners
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from ui_pages.common import footer_license, page_wrap


CONFIG_DIR = "/config/pv_mining_addon"
DASHB_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
DASHB_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
CONFIG_PATH = MAIN_CFG  # für load_config()

SHOW_INACTIVE_REMINDERS = True   # 1W-“Erinnerung” für inaktive Lasten
GHOST_KW = 0.001                 # 1 Watt in kW

GAUGE_DOMAIN = {"x": [0.06, 0.94], "y": [0.00, 1.00]}
GAUGE_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=28, b=0))
GAUGE_NUMBER_FONT = {"font": {"size": 56}}
GAUGE_TITLE_FONT  = {"font": {"size": 18}}
GAUGE_TICK_FONT   = {"size": 12}

def _heater_power_kw():
    try:
        eid = heater_resolve_entity("input_heizstab_cache")  # Prozent (0–100) aus HA input_number
        pct = float(get_sensor_value(eid) or 0.0)
        max_kw = float(heat_get_var("max_power_heater", 0.0) or 0.0)
        return max(0.0, (pct/100.0) * max_kw)
    except Exception:
        return 0.0

def _wallbox_power_kw():
    # bei dir später aus Store/Sensor – vorerst 0 = inaktiv → Ghost
    return 0.0

def _battery_power_kw():
    # bei dir später aus Store/Sensor – vorerst 0 = inaktiv → Ghost
    return max(_battery_power_kw_live(), 0.0)

def _battery_soc_percent():
    """SoC in % aus battery_store (None, falls nicht konfiguriert/lesbar)."""
    try:
        eid = bat_get("soc_entity", "") or ""
        if not eid:
            return None
        v = get_sensor_value(eid)
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _battery_power_kw_live():
    """
    Battery-Leistung in kW:
      - wenn power_entity gesetzt: diese verwenden (W→kW normalisieren, falls nötig)
      - sonst: aus Voltage*Current berechnen (A*V/1000), inkl. Vorzeichen (I<0 = Entladen)
    """
    # 1) direkter Power-Sensor?
    pwr_eid = bat_get("power_entity", "") or ""
    if pwr_eid:
        try:
            val = float(get_sensor_value(pwr_eid))
            # Heuristik: viele Sensoren liefern W → in kW umrechnen
            if abs(val) > 300:  # >300 W ⇒ vermutlich W
                val = val / 1000.0
            return val
        except Exception:
            pass

    # 2) aus V * I
    v_eid = bat_get("voltage_entity", "") or ""
    i_eid = bat_get("current_entity", "") or ""
    try:
        v = float(get_sensor_value(v_eid)) if v_eid else None
        i = float(get_sensor_value(i_eid)) if i_eid else None
    except Exception:
        v, i = None, None

    if v is None or i is None:
        return 0.0

    # I > 0 = Laden (positiv), I < 0 = Entladen (negativ)
    return (v * i) / 1000.0

def _battery_axis_max_kw() -> float:
    """
    Max. Anzeigebereich der Batterie-Gauge (kW).
    Nimmt – wenn vorhanden – `battery_store.max_power_kw`, sonst Default 5.0.
    """
    try:
        v = bat_get("max_power_kw", None)
        if v is None:
            return 5.0
        return max(float(v), 0.5)
    except Exception:
        return 5.0

# ------------------------------
# Sensor-Resolver
# ------------------------------
def resolve_sensor_id(kind: str) -> str:
    # Minimalvariante: nur neue Keys (kein Legacy)
    def _mget(path, key):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(key) or "").strip()
    return _mget(DASHB_OVR, kind) or _mget(DASHB_DEF, kind)

def _dot(color, size="1em"):
    return html.Span(
        "",
        style={
            "display": "inline-block",
            "width": size,
            "height": size,
            "borderRadius": "50%",
            "backgroundColor": color,
            "marginRight": "8px",
            # slight negative to sit nicely on the baseline
            "verticalAlign": "-0.15em",
        },
    )

def _icon(kind: str):
    # nice, readable defaults
    if kind == "temp":
        ch, color = "🌡️", "#d35400"
    elif kind == "btc":
        ch, color = "₿", "#f7931a"
    elif kind == "hash":
        ch, color = "🖥️", "#444444"
    else:
        ch, color = "•", "#444444"
    return html.Span(
        ch,
        style={
            "marginRight": "8px",
            "fontSize": "1.1em",
            "lineHeight": "1",
            "verticalAlign": "-0.1em",
            "color": color,
            "fontWeight": "600" if kind == "btc" else "400",
        },
    )


def _fmt_price(v):
    # 3 Nachkommastellen, mit Komma statt Punkt (AT/DE-Style)
    return f"{v:.3f}".replace(".", ",")


def _fmt_temp(v, unit="°C"):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if unit == "K":
        v = v + 273.15
    return f"{v:.2f} {unit}"

def _fmt_kw(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = 0.0
    # Komma-Format gewünscht? -> die nächste Zeile einkommentieren:
    # return f"{x:.2f} kW".replace(".", ",")
    return f"{x:.2f} kW"

def _pv_cost_per_kwh() -> float:
    """
    Opportunitätskosten der PV gemäß Settings:
    - policy: zero | feedin
    - feedin: (Vergütung - fee_up) nicht negativ
    """
    try:
        policy = (set_get("pv_cost_policy", "zero") or "zero").lower()
        if policy != "feedin":
            return 0.0

        mode = (set_get("feedin_price_mode", "fixed") or "fixed").lower()
        if mode == "sensor":
            sens = set_get("feedin_price_sensor", "") or ""
            try:
                val = float(get_sensor_value(sens) or 0.0) if sens else 0.0
            except Exception:
                val = float(set_get("feedin_price_value", 0.0) or 0.0)
        else:
            val = float(set_get("feedin_price_value", 0.0) or 0.0)

        fee_up = float(elec_get("network_fee_up_value", 0.0) or 0.0)
        return max(val - fee_up, 0.0)
    except Exception:
        return 0.0

def _thresh(path: str, default: float) -> float:
    try:
        return float(set_get(path, default) or default)
    except Exception:
        return default

def _price_color_market(v: float) -> str:
    """
    Farbe für Marktpreis (inkl. Netz). Schwellwerte in €/kWh.
    Optional konfigurierbar in pv_mining_local_config.yaml:
      ui_price_thresholds:
        market:   { green_eur_kwh: 0.15, yellow_eur_kwh: 0.30 }
    """
    g = _thresh("ui_price_thresholds.market.green_eur_kwh", 0.15)
    y = _thresh("ui_price_thresholds.market.yellow_eur_kwh", 0.30)
    return "#27ae60" if v <= g else ("#f39c12" if v <= y else "#e74c3c")

def _price_color_blended(v: float) -> str:
    """
    Farbe für PV-adjusted (Net load cost). Schwellwerte i. d. R. niedriger als Market.
    Optional konfigurierbar:
      ui_price_thresholds:
        blended:  { green_eur_kwh: 0.10, yellow_eur_kwh: 0.22 }
    """
    g = _thresh("ui_price_thresholds.blended.green_eur_kwh", 0.10)
    y = _thresh("ui_price_thresholds.blended.yellow_eur_kwh", 0.22)
    return "#27ae60" if v <= g else ("#f39c12" if v <= y else "#e74c3c")


# ------------------------------
# Farben
# ------------------------------
COLORS = {
    "inflow": "#FFD700",
    "cooling": "#5DADE2",
    "miners":  "#FF9900",
    "battery": "#8E44AD",
    "heater": "#3399FF",
    "wallbox": "#33CC66",
    "grid_feed": "#FF3333",
    "load": "#A0A0A0",
    "inactive": "#DDDDDD"
}

# ------------------------------
# Callbacks
# ------------------------------
def register_callbacks(app):
    @app.callback(
        Output("sankey-diagram", "figure"),
        Input("pv-update", "n_intervals")
    )
    def update_sankey(_):
        # --- Eingänge (PV/Grid) ---
        pv_id = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        pv_val = float(get_sensor_value(pv_id) or 0.0)
        grid_val = float(get_sensor_value(grid_id) or 0.0)
        feed_val = float(get_sensor_value(feed_id) or 0.0)

        inflow_base = max(pv_val + grid_val, 0.0)

        # --- Batterie: + = Laden (Senke), - = Entladen (Quelle) ---
        bat_pwr = float(_battery_power_kw_live() or 0.0)
        bat_charge_kw = max(bat_pwr, 0.0)  # Senke
        bat_discharge_kw = max(-bat_pwr, 0.0)  # Quelle

        # Verfügbare Energie für Verbraucher = PV+Grid (+ Entladung)
        inflow_eff = inflow_base + bat_discharge_kw

        # PV / Grid %-Anteile weiterhin nur auf PV+Grid
        pv_pct, grid_pct = (0.0, 0.0)
        if inflow_base > 0:
            pv_pct = round(pv_val / inflow_base * 100, 1)
            grid_pct = round(grid_val / inflow_base * 100, 1)

        # ---- Miner (dynamisch) ----
        try:
            miners = list_miners()
        except Exception:
            miners = []

        miner_entries = []
        sum_active_miners_kw = 0.0
        for m in miners:
            name = (m.get("name") or "Miner").strip()
            pkw = float(m.get("power_kw") or 0.0)
            active = bool(m.get("enabled")) and bool(m.get("on"))
            if active:
                miner_entries.append({"name": name, "kw": max(pkw, 0.0), "color": COLORS["miners"], "ghost": False})
                sum_active_miners_kw += max(pkw, 0.0)
            elif SHOW_INACTIVE_REMINDERS:
                miner_entries.append({"name": name, "kw": GHOST_KW, "color": COLORS["inactive"], "ghost": True})

        # ---- Weitere Lasten ----
        heater_kw = _heater_power_kw()
        wallbox_kw = _wallbox_power_kw()
        cooling_kw = 0.0
        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        cooling = get_cooling() if cooling_feature else None
        if cooling_feature and cooling:
            cooling_kw = float(cooling.get("power_kw") or 0.0) if bool(cooling.get("on")) else 0.0

        # ---- House usage = Rest (ohne Ghosts) ----
        known_real = (
                sum_active_miners_kw
                + max(feed_val, 0.0)
                + heater_kw + wallbox_kw + cooling_kw
                + bat_charge_kw  # Laden als Last mitzählen
        )
        house_kw = max(inflow_eff - known_real, 0.0)

        # ---- Node/Link-Builder ----
        node_labels, node_colors = [], []
        link_source, link_target, link_value, link_color = [], [], [], []

        def add_node(label, color):
            idx = len(node_labels)
            node_labels.append(label)
            node_colors.append(color)
            return idx

        def add_link(s, t, v, color):
            link_source.append(s)
            link_target.append(t)
            link_value.append(max(float(v or 0.0), 0.0))
            link_color.append(color)

        # Batterie (als Quelle beim Entladen) zuerst anlegen, damit sie links landet
        battery_src_idx = None
        if bat_discharge_kw > 0.0:
            battery_src_idx = add_node(f"Battery (discharge)<br>{_fmt_kw(bat_discharge_kw)}", COLORS["battery"])

        # Energy Inflow (zeigt die effektiv verfügbare Leistung)
        inflow_idx = add_node(
            f"Energy Inflow<br>{_fmt_kw(inflow_eff)}<br>PV: {pv_pct}% · Grid: {grid_pct}%",
            COLORS["inflow"]
        )

        # Link von Batterie ➜ Inflow, wenn entladen wird
        if battery_src_idx is not None:
            add_link(battery_src_idx, inflow_idx, bat_discharge_kw, COLORS["battery"])

        # Cooling (optional)
        if cooling_feature:
            cooling_is_active = cooling_kw > 0.0
            cooling_kw_eff = cooling_kw if cooling_is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
            if cooling_is_active or SHOW_INACTIVE_REMINDERS:
                cooling_color = COLORS["cooling"] if cooling_is_active else COLORS["inactive"]
                cooling_idx = add_node(f"Cooling circuit<br>{_fmt_kw(cooling_kw)}", cooling_color)
                add_link(inflow_idx, cooling_idx, cooling_kw_eff, cooling_color)

        # Miner
        for me in miner_entries:
            idx = add_node(f"{me['name']}<br>{_fmt_kw(me['kw'])}", me["color"])
            add_link(inflow_idx, idx, me["kw"], me["color"])

        # Heater
        heater_is_active = heater_kw > 0.0
        heater_kw_eff = heater_kw if heater_is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
        if heater_is_active or SHOW_INACTIVE_REMINDERS:
            heater_color = COLORS["heater"] if heater_is_active else COLORS["inactive"]
            heater_idx = add_node(f"Water Heater<br>{_fmt_kw(heater_kw)}", heater_color)
            add_link(inflow_idx, heater_idx, heater_kw_eff, heater_color)

        # Wallbox
        wallbox_is_active = wallbox_kw > 0.0
        wallbox_kw_eff = wallbox_kw if wallbox_is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
        if wallbox_is_active or SHOW_INACTIVE_REMINDERS:
            wallbox_color = COLORS["wallbox"] if wallbox_is_active else COLORS["inactive"]
            wallbox_idx = add_node(f"Wallbox<br>{_fmt_kw(wallbox_kw)}", wallbox_color)
            add_link(inflow_idx, wallbox_idx, wallbox_kw_eff, wallbox_color)

        # Battery (als Senke beim Laden)
        if bat_charge_kw > 0.0 or SHOW_INACTIVE_REMINDERS:
            is_active = bat_charge_kw > 0.0
            bat_kw_eff = bat_charge_kw if is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
            if is_active or SHOW_INACTIVE_REMINDERS:
                bat_color = COLORS["battery"] if is_active else COLORS["inactive"]
                bat_sink_idx = add_node(f"Battery (charge)<br>{_fmt_kw(bat_charge_kw)}", bat_color)
                add_link(inflow_idx, bat_sink_idx, bat_kw_eff, bat_color)

        # Grid Feed-in
        feed_is_active = feed_val > 0.0
        feed_kw_eff = feed_val if feed_is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
        if feed_is_active or SHOW_INACTIVE_REMINDERS:
            feed_color = COLORS["grid_feed"] if feed_is_active else COLORS["inactive"]
            feed_idx = add_node(f"Grid Feed-in<br>{_fmt_kw(feed_val)}", feed_color)
            add_link(inflow_idx, feed_idx, feed_kw_eff, feed_color)

        # House usage (kein Ghost)
        house_idx = add_node(f"House usage<br>{_fmt_kw(house_kw)}", COLORS["load"])
        add_link(inflow_idx, house_idx, house_kw, COLORS["load"])

        # Figure
        fig = go.Figure(data=[go.Sankey(
            valueformat=".3f",
            valuesuffix=" kW",
            node=dict(
                label=node_labels,
                pad=30, thickness=25,
                line=dict(color="black", width=0.5),
                color=node_colors
            ),
            link=dict(
                source=link_source,
                target=link_target,
                value=link_value,
                color=link_color
            )
        )])

        fig.update_layout(
            font=dict(size=14, color="black"),
            plot_bgcolor="rgba(0,0,0,0)",  # ⟵ transparent
            paper_bgcolor="rgba(0,0,0,0)",  # ⟵ transparent
            margin=dict(l=20, r=20, t=40, b=20)
        )
        fig.update_traces(hoverlabel=dict(bgcolor="white"))

        return fig

    @app.callback(
        Output("pv-gauge", "figure"),
        Output("grid-gauge", "figure"),
        Output("feed-gauge", "figure"),
        Input("pv-update", "n_intervals"),
    )
    def update_gauges(_):
        def safe_val(eid):
            try:
                return float(get_sensor_value(eid) or 0.0) if eid else 0.0
            except Exception:
                return 0.0

        pv_id = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        pv_val = safe_val(pv_id)
        grid_val = safe_val(grid_id)
        feed_val = safe_val(feed_id)

        def build_gauge(value, title, color, axis_max=5):
            ticks = [0, axis_max / 2, axis_max]
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=float(value or 0),
                number=GAUGE_NUMBER_FONT | {"valueformat": ".2f"},
                title={"text": title, **GAUGE_TITLE_FONT},
                domain=GAUGE_DOMAIN,
                gauge={
                    "axis": {
                        "range": [0, axis_max],
                        "tickvals": ticks,
                        "ticktext": [str(int(t)) if t.is_integer() else f"{t:g}" for t in ticks],
                        "tickfont": GAUGE_TICK_FONT,
                    },
                    "bar": {"color": color},
                    "steps": [
                        {"range": [0, axis_max / 2], "color": "#e0f7e0"},
                        {"range": [axis_max / 2, axis_max], "color": "#c0e0c0"},
                    ],
                }
            ))
            fig.update_layout(**GAUGE_LAYOUT)
            return fig

        return (
            build_gauge(pv_val, "PV production (kW)", "green"),
            build_gauge(grid_val, "Grid consumption (kW)", "orange"),
            build_gauge(feed_val, "Grid feed-in (kW)", "red"),
        )

    @app.callback(
        Output("battery-gauge", "figure"),
        Input("pv-update", "n_intervals"),
    )
    def update_battery(_n):
        def f(eid, d=0.0):
            try:
                return float(get_sensor_value(eid) or d) if eid else d
            except Exception:
                return d

        # Leistung aus V*I (kW)
        vdc = f(bat_get("voltage_entity", ""))
        idc = f(bat_get("current_entity", ""))
        pkw = (vdc * idc) / 1000.0

        axis_max = _battery_axis_max_kw()
        value = min(max(abs(pkw), 0.0), axis_max)

        # Farblogik
        eps = 0.02
        if pkw > eps:
            bar_color = "#27ae60"  # laden
        elif pkw < -eps:
            bar_color = "#e74c3c"  # entladen
        else:
            bar_color = "#999999"  # idle

        ticks = [0, axis_max / 2, axis_max]
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=value,
            number=GAUGE_NUMBER_FONT | {"valueformat": ".2f"},
            title={"text": "Battery power (kW)", **GAUGE_TITLE_FONT},
            domain=GAUGE_DOMAIN,
            gauge={
                "axis": {
                    "range": [0, axis_max],
                    "tickvals": ticks,
                    "ticktext": [str(int(t)) if float(t).is_integer() else f"{t:g}" for t in ticks],
                    "tickfont": GAUGE_TICK_FONT,
                },
                "bar": {"color": bar_color},
                "steps": [
                    {"range": [0, axis_max / 2], "color": "#e0f7e0"},
                    {"range": [axis_max / 2, axis_max], "color": "#c0e0c0"},
                ],
            }
        ))
        fig.update_layout(**GAUGE_LAYOUT)
        return fig

    @app.callback(
        Output("btc-price", "children"),
        Output("btc-hashrate", "children"),
        Input("btc-refresh", "n_intervals")
    )
    def update_btc_display(_):
        config = load_yaml(os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml"), {})
        entities = config.get("entities", {})
        price = entities.get("sensor_btc_price")
        hashrate = entities.get("sensor_btc_hashrate")

        if isinstance(price, (int, float)):
            price_str = f"BTC Price: ${price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            price_str = "BTC Price: –"

        if isinstance(hashrate, (int, float)):
            hashrate_str = f"Hashrate: {hashrate:,.2f} TH/s".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            hashrate_str = "Hashrate: –"

        return (
            html.Span([_icon("btc"), price_str]),
            html.Span([_icon("hash"), hashrate_str]),
        )

    @app.callback(
        Output("elec-market", "children"),
        Output("elec-price", "children"),
        Input("pv-update", "n_intervals")  # alle 10s aktualisieren
    )
    def update_energy_prices(_):
        sym = currency_symbol()

        # --- 1) Market price inkl. Netzgebühr (down) ---
        base = current_price() or 0.0
        fee_down = float(elec_get("network_fee_down_value", 0.0) or 0.0)
        market = (base or 0.0) + fee_down
        market_txt = f"Market Price: {_fmt_price(market)} {sym}/kWh"
        market_color = _price_color_market(market)
        market_out  = html.Span([_dot(market_color, "1em"), market_txt])

        # --- 2) PV-adjusted (aktueller Mix PV/Grid) ---
        try:
            pv_id = resolve_sensor_id("pv_production")
            grid_id = resolve_sensor_id("grid_consumption")
            pv_val = float(get_sensor_value(pv_id) or 0.0)
            grid_val = float(get_sensor_value(grid_id) or 0.0)
            inflow = max(pv_val + grid_val, 0.0)

            if inflow > 0.0:
                pv_share = max(min(pv_val / inflow, 1.0), 0.0)
                grid_share = 1.0 - pv_share
            else:
                pv_share, grid_share = 0.0, 1.0

            pv_cost = _pv_cost_per_kwh()
            blended = pv_share * pv_cost + grid_share * market
            blended_color = _price_color_blended(blended)
            blended_txt = f"Net load cost (PV-adjusted): {_fmt_price(blended)} {sym}/kWh"
            blended_out = html.Span([_dot(blended_color, "1em"), blended_txt])
        except Exception:
            blended_out = html.Span([_dot("#888", "1em"), "Net load cost (PV-adjusted): –"])

        return market_out, blended_out

    @app.callback(
        Output("dashboard-water-temp", "children"),
        Input("pv-update", "n_intervals")  # alle 10s
    )
    def update_dashboard_water_temp(_):
        entity_id = heater_resolve_entity("input_warmwasser_cache")
        if not entity_id:
            return html.Span([_icon("temp"), "Water Temp: –"])
        val = get_sensor_value(entity_id)
        unit = heat_get_var("heat_unit", "°C")
        return html.Span([_icon("temp"), f"Water Temp: {_fmt_temp(val, unit)}"])


# ------------------------------
# Layout
# ------------------------------
def layout():
    return page_wrap([
        html.H1([
            "PV-mining dashboard — by ",
            html.A(
                "BitcoinSolution.at",
                href="https://www.bitcoinsolution.at",
                target="_blank",
                rel="noopener noreferrer",
                style={"textDecoration": "none"}
            )
        ], className="page-title"),

        dcc.Graph(id="sankey-diagram", figure=go.Figure()),

        html.Div([
            dcc.Graph(id="pv-gauge",
                      style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="grid-gauge",
                      style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="feed-gauge",
                      style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="battery-gauge",
                      style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"},
                      config={"displayModeBar": False}),
        ], style={"display": "flex", "flexWrap": "wrap", "justifyContent": "center", "gap": "20px"}),

        dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),

        html.Div([
            html.Div(id="elec-market", className="footer-stat"),  # NEW: Marktpreis inkl. Netz
            html.Div(id="elec-price", className="footer-stat"),  # PV-adjusted (bisheriger)
            html.Div(id="dashboard-water-temp", className="footer-stat"),
            html.Div(id="btc-price", className="footer-stat"),
            html.Div(id="btc-hashrate", className="footer-stat"),
        ], className="footer-stats"),
        dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0),
        footer_license()
    ])

