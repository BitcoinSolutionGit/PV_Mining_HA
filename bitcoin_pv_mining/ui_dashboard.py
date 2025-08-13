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

CONFIG_DIR = "/config/pv_mining_addon"
DASHB_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
DASHB_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
CONFIG_PATH = MAIN_CFG  # für load_config()

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

# ------------------------------
# Farben
# ------------------------------
COLORS = {
    "inflow": "#FFD700",
    "miners":  "#FF9900",
    "battery": "#8E44AD",
    "heater": "#3399FF",
    "wallbox": "#33CC66",
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
        # --- Eingänge holen ---
        pv_id   = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")

        pv_val   = float(get_sensor_value(pv_id)   or 0)
        grid_val = float(get_sensor_value(grid_id) or 0)
        inflow   = max(pv_val + grid_val, 0.0)

        # Prozentanzeige
        if inflow > 0:
            pv_pct   = round(pv_val   / inflow * 100, 1)
            grid_pct = round(grid_val / inflow * 100, 1)
        else:
            pv_pct = grid_pct = 0.0

        # Feature-Flags
        config = load_yaml(os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml"), {})
        flags  = config.get("feature_flags", {}) or {}

        # Nodes
        node_labels = [
            f"Energy Inflow<br>PV: {pv_pct}%<br>Grid: {grid_pct}%",  # 0
            "Miners",           # 1
            "Battery",          # 2
            "Water Heater",     # 3
            "Wallbox",          # 4
            "House usage"       # 5
        ]
        node_colors = [
            COLORS["inflow"],
            COLORS["miners"] if flags.get("miners_active") else COLORS["inactive"],
            COLORS["battery"] if flags.get("battery_active") else COLORS["inactive"],
            COLORS["heater"] if flags.get("heater_active") else COLORS["inactive"],
            COLORS["wallbox"] if flags.get("wallbox_active") else COLORS["inactive"],
            COLORS["load"]
        ]

        # Aktive Ziele ermitteln (mind. Load)
        targets = []
        if flags.get("miners_active"): targets.append(1)
        if flags.get("battery_active"): targets.append(2)
        if flags.get("heater_active"):  targets.append(3)
        if flags.get("wallbox_active"): targets.append(4)
        # Load immer als Fallback-Ziel
        if 5 not in targets:
            targets.append(5)

        # Gleichmäßig verteilen (einfach & robust)
        n = len(targets) if inflow > 0 else 1
        per = inflow / n

        # Links aufbauen
        link_source = []
        link_target = []
        link_value  = []
        link_color  = []

        color_map = {
            1: ("#FF9900" if flags.get("miners_active") else "#DDDDDD"),
            2: ("#8E44AD" if flags.get("battery_active") else "#DDDDDD"),
            3: ("#3399FF" if flags.get("heater_active")  else "#DDDDDD"),
            4: ("#33CC66" if flags.get("wallbox_active") else "#DDDDDD"),
            5: "#A0A0A0",
        }

        for t in targets:
            link_source.append(0)      # always from inflow node
            link_target.append(t)
            link_value.append(per)
            link_color.append(color_map[t])

        fig = go.Figure(data=[go.Sankey(
            node=dict(
                label=node_labels,
                pad=30,
                thickness=25,
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
            text = "Strompreis: –"
        else:
            text = f"Strompreis: {_fmt_price(v)} {sym}/kWh"
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
        html.H1("PV-mining dashboard"),

        dcc.Graph(id="sankey-diagram", figure=go.Figure()),

        html.Div([
            dcc.Graph(id="pv-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="grid-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="feed-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            html.Div(id="dashboard-water-temp", style={"textAlign": "center", "fontWeight": "bold"})
        ], style={"display": "flex", "flexDirection": "row", "flexWrap": "wrap", "justifyContent": "center", "gap": "20px"}),

        dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),
        html.Div([
            html.Div(id="elec-price", style={"textAlign": "center", "fontWeight": "bold"}),
            html.Div(id="btc-price", style={"textAlign": "center", "fontWeight": "bold"}),
            html.Div(id="btc-hashrate", style={"textAlign": "center", "fontWeight": "bold"})
        ], style={"display": "flex", "justifyContent": "center", "gap": "40px", "marginTop": "20px"}),
        dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0)
    ])

