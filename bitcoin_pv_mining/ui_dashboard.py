import os
import yaml
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go
from services.ha_sensors import get_sensor_value
from services.utils import load_yaml  # nutzt deine utils.py

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
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
    return _mget(SENS_OVR, kind) or _mget(SENS_DEF, kind)

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
            "Heater",           # 3
            "Wallbox",          # 4
            "Total Load"        # 5
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
            dcc.Graph(id="feed-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"})
        ], style={"display": "flex", "flexDirection": "row", "flexWrap": "wrap", "justifyContent": "center", "gap": "20px"}),

        dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),
        html.Div([
            html.Div(id="btc-price", style={"textAlign": "center", "fontWeight": "bold"}),
            html.Div(id="btc-hashrate", style={"textAlign": "center", "fontWeight": "bold"})
        ], style={"display": "flex", "justifyContent": "center", "gap": "40px", "marginTop": "20px"}),
        dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0)
    ])

