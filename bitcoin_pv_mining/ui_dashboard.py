import os
import yaml
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.graph_objects as go
from ha_sensors import get_sensor_value

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

COLORS = {
    "pv": "#FFD700",
    "heater": "#3399FF",
    "wallbox": "#33CC66",
    "battery": "#FF9900",
    "load": "#A0A0A0",
    "inactive": "#DDDDDD"
}

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print("[WARN] Config file missing or invalid:", e)
        return {}

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
        Input("pv-update", "n_intervals")
    )
    def update_gauges(_):
        config = load_config()
        pv_id = config.get("entities", {}).get("sensor_pv_production")
        load_id = config.get("entities", {}).get("sensor_load_consumption")
        pv_val = get_sensor_value(pv_id) if pv_id else 0
        load_val = get_sensor_value(load_id) if load_id else 0

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
            build_gauge(load_val, "Load consumption (kW)", "orange")
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
        hashrate_str = f"Hashrate: {hashrate:,.2f} TH/s".replace(",", "X").replace(".", ",").replace("X",
                                                                                                     ".") if hashrate else "–"
        return price_str, hashrate_str

layout = html.Div([
    html.H1("PV-mining dashboard"),
    dcc.Graph(id="sankey-diagram", figure=go.Figure()),
    html.Div([
        dcc.Graph(id="pv-gauge", style={
            "flex": "1 1 300px",
            "minWidth": "300px",
            "maxWidth": "500px",
            "height": "300px"
        }),
        dcc.Graph(id="load-gauge", style={
            "flex": "1 1 300px",
            "minWidth": "300px",
            "maxWidth": "500px",
            "height": "300px"
        })
    ], style={
        "display": "flex",
        "flexDirection": "row",
        "flexWrap": "wrap",
        "justifyContent": "center",
        "gap": "20px"
    }),

    dcc.Interval(id="pv-update", interval=10_000, n_intervals=0),

    html.Div([
        html.Div(id="btc-price", style={"textAlign": "center", "fontWeight": "bold"}),
        html.Div(id="btc-hashrate", style={"textAlign": "center", "fontWeight": "bold"})
    ], style={"display": "flex", "justifyContent": "center", "gap": "40px", "marginTop": "20px"}),

    dcc.Interval(id="btc-refresh", interval=60_000, n_intervals=0)

])