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
    """
    kind ∈ {"pv_production","load_consumption","grid_feed_in"}
    Priorität: sensors.local.yaml -> sensors.yaml -> pv_mining_local_config.yaml/entities
    """
    mapping_def = load_yaml(SENS_DEF, {}).get("mapping", {})
    mapping_ovr = load_yaml(SENS_OVR, {}).get("mapping", {})

    # override gewinnt
    sid = (mapping_ovr.get(kind) or mapping_def.get(kind) or "").strip()
    if sid:
        return sid

    # Fallback auf alte entities
    cfg = load_yaml(MAIN_CFG, {})
    ents = cfg.get("entities", {})
    fallback_keys = {
        "pv_production": "sensor_pv_production",
        "load_consumption": "sensor_load_consumption",
        "grid_feed_in": "sensor_grid_feed_in",
    }
    return (ents.get(fallback_keys[kind], "") or "").strip()

# ------------------------------
# Farben
# ------------------------------
COLORS = {
    "pv": "#FFD700",
    "heater": "#3399FF",
    "wallbox": "#33CC66",
    "battery": "#FF9900",
    "load": "#A0A0A0",
    "inactive": "#DDDDDD"
}

# ------------------------------
# Config-Loader
# ------------------------------
def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print("[WARN] Config file missing or invalid:", e)
        return {}

# ------------------------------
# Callbacks
# ------------------------------
def register_callbacks(app):
    @app.callback(
        Output("sankey-diagram", "figure"),
        Input("pv-update", "n_intervals")
    )
    def update_sankey(_):
        config = load_config()
        flags = config.get("feature_flags", {})

        node_labels = ["PV", "Heater", "Wallbox", "Battery", "Load"]
        node_colors = [
            COLORS["pv"],
            COLORS["heater"] if flags.get("heater_active") else COLORS["inactive"],
            COLORS["wallbox"] if flags.get("wallbox_active") else COLORS["inactive"],
            COLORS["battery"] if flags.get("battery_active") else COLORS["inactive"],
            COLORS["load"]
        ]

        fig = go.Figure(data=[go.Sankey(
            node=dict(
                label=node_labels,
                pad=30,
                thickness=25,
                line=dict(color="black", width=0.5),
                color=node_colors
            ),
            link=dict(
                source=[0, 0, 0, 0],
                target=[1, 2, 3, 4],
                value=[4, 3, 2, 1],
                color=[
                    COLORS["heater"] if flags.get("heater_active") else COLORS["inactive"],
                    COLORS["wallbox"] if flags.get("wallbox_active") else COLORS["inactive"],
                    COLORS["battery"] if flags.get("battery_active") else COLORS["inactive"],
                    COLORS["load"]
                ]
            )
        )])

        fig.update_layout(
            font=dict(size=14, color="black"),
            plot_bgcolor='white',
            paper_bgcolor='white',
            margin=dict(l=20, r=20, t=40, b=20)
        )

        return fig

    @app.callback(
        Output("pv-gauge", "figure"),
        Output("load-gauge", "figure"),
        Output("feed-gauge", "figure"),
        Input("pv-update", "n_intervals")
    )
    def update_gauges(_):
        pv_id = resolve_sensor_id("pv_production")
        load_id = resolve_sensor_id("load_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        pv_val = get_sensor_value(pv_id) if pv_id else 0
        load_val = get_sensor_value(load_id) if load_id else 0
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
            build_gauge(load_val, "Load consumption (kW)", "orange"),
            build_gauge(feed_val, "Grid feed-in (kW)", "red")
        )

    @app.callback(
        Output("btc-price", "children"),
        Output("btc-hashrate", "children"),
        Input("btc-refresh", "n_intervals")
    )
    def update_btc_display(_):
        config = load_config()
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
            dcc.Graph(id="load-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"}),
            dcc.Graph(id="feed-gauge", style={"flex": "1 1 300px", "minWidth": "300px", "maxWidth": "500px", "height": "300px"})
        ], style={"display": "flex", "flexDirection": "row", "flexWrap": "wrap", "justifyContent": "center", "gap": "20px"}),

        dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),
        html.Div([
            html.Div(id="btc-price", style={"textAlign": "center", "fontWeight": "bold"}),
            html.Div(id="btc-hashrate", style={"textAlign": "center", "fontWeight": "bold"})
        ], style={"display": "flex", "justifyContent": "center", "gap": "40px", "marginTop": "20px"}),
        dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0)
    ])

