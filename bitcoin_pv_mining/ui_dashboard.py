import os
import yaml
import traceback
import plotly.graph_objects as go

from dash import html, dcc
from dash.dependencies import Input, Output

from services.ha_sensors import get_sensor_value
from services.utils import load_yaml
from services.electricity_store import current_price, currency_symbol, price_color
from services.heater_store import resolve_entity_id as heater_resolve_entity, get_var as heat_get_var
from services.miners_store import list_miners
from services.cooling_store import get_cooling
from services.settings_store import get_var as set_get
from ui_pages.common import footer_license



CONFIG_DIR = "/config/pv_mining_addon"
DASHB_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
DASHB_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
CONFIG_PATH = MAIN_CFG  # für load_config()

SHOW_INACTIVE_REMINDERS = True   # 1W-“Erinnerung” für inaktive Lasten
GHOST_KW = 0.001                 # 1 Watt in kW

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
    return 0.0

# ------------------------------
# Sensor-Resolver
# ------------------------------
def resolve_sensor_id(kind: str) -> str:
    # Minimalvariante: nur neue Keys (kein Legacy)
    def _mget(path, key):
        m = (load_yaml(path, {}).get("mapping", {}) or {})
        return (m.get(key) or "").strip()
    return _mget(DASHB_OVR, kind) or _mget(DASHB_DEF, kind)

def _dot(color):
    return html.Span("", style={
        "display": "inline-block", "width": "10px", "height": "10px",
        "borderRadius": "50%", "backgroundColor": color, "marginRight": "8px",
        "verticalAlign": "middle"
    })

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
        # --- Eingänge ---
        pv_id = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        pv_val = float(get_sensor_value(pv_id) or 0.0)
        grid_val = float(get_sensor_value(grid_id) or 0.0)
        feed_val = float(get_sensor_value(feed_id) or 0.0)
        inflow = max(pv_val + grid_val, 0.0)

        pv_pct, grid_pct = (0.0, 0.0)
        if inflow > 0:
            pv_pct = round(pv_val / inflow * 100, 1)
            grid_pct = round(grid_val / inflow * 100, 1)

        # ---- Miner dynamisch ----
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

        # ---- Weitere Lasten (Heater/Wallbox/Battery) ----
        heater_kw = _heater_power_kw()
        wallbox_kw = _wallbox_power_kw()
        battery_kw = _battery_power_kw()

        # ---- Cooling circuit (nur wenn Feature aktiv) ----
        cooling_kw = 0.0
        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        cooling = get_cooling() if cooling_feature else None
        if cooling_feature and cooling:
            cooling_kw = float(cooling.get("power_kw") or 0.0) if bool(cooling.get("on")) else 0.0

        # ---- House usage = Rest (ohne Ghosts) ----
        known_real = (
                sum_active_miners_kw
                + max(feed_val, 0.0)
                + heater_kw + wallbox_kw + battery_kw
                + cooling_kw
        )
        house_kw = max(inflow - known_real, 0.0)

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

        # Inflow
        inflow_idx = add_node(
            f"Energy Inflow<br>{_fmt_kw(inflow)}<br>PV: {pv_pct}% · Grid: {grid_pct}%",
            COLORS["inflow"]
        )

        # Cooling (nur wenn Feature aktiv)
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

        # Battery
        battery_is_active = battery_kw > 0.0
        battery_kw_eff = battery_kw if battery_is_active else (GHOST_KW if SHOW_INACTIVE_REMINDERS else 0.0)
        if battery_is_active or SHOW_INACTIVE_REMINDERS:
            battery_color = COLORS["battery"] if battery_is_active else COLORS["inactive"]
            battery_idx = add_node(f"Battery<br>{_fmt_kw(battery_kw)}", battery_color)
            add_link(inflow_idx, battery_idx, battery_kw_eff, battery_color)

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
            plot_bgcolor='white',
            paper_bgcolor='white',
            margin=dict(l=20, r=20, t=40, b=20)
        )
        fig.update_traces(hoverlabel=dict(bgcolor="white"))

        return fig

    @app.callback(
        Output("pv-gauge", "figure"),
        Output("grid-gauge", "figure"),
        Output("feed-gauge", "figure"),
        Input("pv-update", "n_intervals")
    )
    def update_gauges(_):
        pv_id = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        pv_val = get_sensor_value(pv_id) if pv_id else 0
        grid_val = get_sensor_value(grid_id) if grid_id else 0
        feed_val = get_sensor_value(feed_id) if feed_id else 0

        def build_gauge(value, title, color):
            return go.Figure(go.Indicator(
                mode="gauge+number",
                value=value or 0,
                title={"text": title},
                gauge={
                    "axis": {"range": [0, 5]},
                    "bar": {"color": color},
                    "steps": [
                        {"range": [0, 2.5], "color": "#e0f7e0"},
                        {"range": [2.5, 5], "color": "#c0e0c0"}
                    ]
                }
            ))

        return (
            build_gauge(pv_val, "PV production (kW)", "green"),
            build_gauge(grid_val, "Grid consumption (kW)", "orange"),
            build_gauge(feed_val, "Grid feed-in (kW)", "red")
        )

    @app.callback(
        Output("btc-price", "children"),
        Output("btc-hashrate", "children"),
        Input("btc-refresh", "n_intervals")
    )
    def update_btc_display(_):
        config = load_yaml(os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml"), {})
        entities = config.get("entities", {})
        price = entities.get("sensor_btc_price", "N/A")
        hashrate = entities.get("sensor_btc_hashrate", "N/A")

        price_str = f"BTC Price: ${price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if price else "–"
        hashrate_str = f"Hashrate: {hashrate:,.2f} TH/s".replace(",", "X").replace(".", ",").replace("X", ".") if hashrate else "–"
        return price_str, hashrate_str

    @app.callback(
        Output("elec-price", "children"),
        Input("pv-update", "n_intervals")  # alle 10s aktualisieren
    )
    def update_electricity_price(_):
        v = current_price()
        sym = currency_symbol()
        color = price_color(v)
        if v is None:
            text = "Energy Price: –"
        else:
            text = f"Energy Price: {_fmt_price(v)} {sym}/kWh"
        return html.Span([_dot(color), text])

    @app.callback(
        Output("dashboard-water-temp", "children"),
        Input("pv-update", "n_intervals")  # alle 10s
    )
    def update_dashboard_water_temp(_):
        entity_id = heater_resolve_entity("input_warmwasser_cache")
        if not entity_id:
            return "Water Temp: –"
        val = get_sensor_value(entity_id)
        unit = heat_get_var("heat_unit", "°C")  # aus heater_store.yaml lesen
        return f"Water Temp: {_fmt_temp(val, unit)}"


# ------------------------------
# Layout
# ------------------------------
def layout():
    return html.Div([
        html.H1([
            "PV-mining dashboard — by ",
            html.A(
                "BitcoinSolution.at",
                href="https://www.bitcoinsolution.at",
                target="_blank",
                rel="noopener noreferrer",
                style={"textDecoration": "none"}  # optional: Link ohne Unterstreichung
            )
        ]),

        dcc.Graph(id="sankey-diagram", figure=go.Figure()),

        html.Div([
            dcc.Graph(id="pv-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="grid-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="feed-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"})
        ], style={"display": "flex", "flexDirection": "row", "flexWrap": "wrap", "justifyContent": "center", "gap": "20px"}),
        dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),

        html.Div([
            html.Div(id="elec-price", className="footer-stat"),
            html.Div(id="dashboard-water-temp", className="footer-stat"),
            html.Div(id="btc-price", className="footer-stat"),
            html.Div(id="btc-hashrate", className="footer-stat"),
        ], className="footer-stats"),
        dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0),
        footer_license()
    ])

