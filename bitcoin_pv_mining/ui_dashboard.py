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
from services.pv_ramp_up import get_pv_ramp_snapshot
from services.settings_store import get_var as set_get
from services.wallbox_store import get_var as wb_get
from services.sensor_mapping import resolve_sensor_id as resolve_runtime_sensor_id
try:
    from services.dev_mock import (
        get_virtual_value,
        effective_entity_key,
        DEV_PV_PRODUCTION,
        DEV_GRID_CONSUMPTION,
        DEV_GRID_FEED_IN,
        DEV_BATTERY_SOC,
        DEV_BATTERY_VOLTAGE,
        DEV_BATTERY_CURRENT,
        DEV_BATTERY_POWER,
        DEV_HEATER_WATER_TEMP,
        DEV_HEATER_PERCENT,
        DEV_WALLBOX_POWER,
        VIRTUAL_BTC_PRICE,
        VIRTUAL_BTC_HASHRATE,
    )
except Exception:
    def get_virtual_value(_key, default=None):
        return default

    def effective_entity_key(entity_id, _mock_key):
        return (entity_id or "").strip()

    DEV_PV_PRODUCTION = "mock:pv_production"
    DEV_GRID_CONSUMPTION = "mock:grid_consumption"
    DEV_GRID_FEED_IN = "mock:grid_feed_in"
    DEV_BATTERY_SOC = "mock:battery_soc"
    DEV_BATTERY_VOLTAGE = "mock:battery_voltage"
    DEV_BATTERY_CURRENT = "mock:battery_current"
    DEV_BATTERY_POWER = "mock:battery_power"
    DEV_HEATER_WATER_TEMP = "mock:heater_water_temp"
    DEV_HEATER_PERCENT = "mock:heater_percent"
    DEV_WALLBOX_POWER = "mock:wallbox_power"
    VIRTUAL_BTC_PRICE = "mock:btc_price"
    VIRTUAL_BTC_HASHRATE = "mock:btc_hashrate"
from ui_pages.common import footer_license, page_wrap


CONFIG_DIR = "/config/pv_mining_addon"
DASHB_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
DASHB_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")
CONFIG_PATH = MAIN_CFG  # für load_config()

GHOST_KW = 0.001                 # 1 Watt in kW

TEXT_PRIMARY = "#f4f7ff"
TEXT_MUTED = "#98a7c4"
PLOT_LINE = "rgba(191, 205, 229, 0.18)"

PV_GREEN = "#29c36a"
BOOST_GREEN = "#8ee57b"
GRID_RED = "#ef5350"
GRID_FEED_RED = "#ff6b6b"
HOUSE_GREY = "#94a3b8"
HEATER_BLUE = "#4da3ff"
BATTERY_PURPLE = "#9b59d0"
COOLING_BLUE = "#7dd3fc"
CONSUMER_ORANGE = "#ff9f1c"
WALLBOX_GREEN = "#33d1c6"
INACTIVE_GREY = "#58657a"

GAUGE_DOMAIN = {"x": [0.06, 0.94], "y": [0.00, 1.00]}
GAUGE_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=28, b=0))
GAUGE_NUMBER_FONT = {"font": {"size": 56, "color": TEXT_PRIMARY}}
GAUGE_TITLE_FONT  = {"font": {"size": 18, "color": TEXT_MUTED}}
GAUGE_TICK_FONT   = {"size": 12, "color": TEXT_MUTED}

def _num(x, d=0.0):
    try: return float(x)
    except: return d

def _heater_power_kw():
    try:
        eid = effective_entity_key(heater_resolve_entity("input_heizstab_cache"), DEV_HEATER_PERCENT)
        pct = float(get_sensor_value(eid) or 0.0)
        max_kw = float(heat_get_var("max_power_heater", 0.0) or 0.0)
        return max(0.0, (pct/100.0) * max_kw)
    except Exception:
        return 0.0

def _wallbox_power_kw():
    try:
        eid = effective_entity_key(wb_get("power_entity", ""), DEV_WALLBOX_POWER)
        return max(float(get_sensor_value(eid) or 0.0), 0.0) if eid else 0.0
    except Exception:
        return 0.0

def _battery_power_kw():
    # bei dir später aus Store/Sensor – vorerst 0 = inaktiv → Ghost
    return max(_battery_power_kw_live(), 0.0)

def _battery_soc_percent():
    """SoC in % aus battery_store (None, falls nicht konfiguriert/lesbar)."""
    try:
        eid = effective_entity_key(bat_get("soc_entity", ""), DEV_BATTERY_SOC)
        if not eid:
            return None
        v = get_sensor_value(eid)
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _battery_capacity_kwh() -> float:
    """
    Nominale Batteriekapazität (kWh) für die Gauge-Skala.
    Quellen (in dieser Reihenfolge):
      - battery_store.capacity_kwh
      - battery_store.nominal_capacity_kwh
      - settings_store: battery.capacity_kwh
      - Fallback: 11.0
    """
    try:
        cap = bat_get("capacity_kwh", None)
        if cap is None:
            cap = bat_get("nominal_capacity_kwh", None)
        if cap is None:
            try:
                cap = set_get("battery.capacity_kwh", None)
            except Exception:
                cap = None
        cap = float(cap) if cap is not None else 15.0
        return max(cap, 0.1)
    except Exception:
        return 15.0

def _battery_power_kw_live():
    """
    Battery-Leistung in kW:
      - wenn power_entity gesetzt: diese verwenden (W→kW normalisieren, falls nötig)
      - sonst: aus Voltage*Current berechnen (A*V/1000), inkl. Vorzeichen (I<0 = Entladen)
    """
    # 1) direkter Power-Sensor?
    pwr_eid = effective_entity_key(bat_get("power_entity", ""), DEV_BATTERY_POWER)
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
    v_eid = effective_entity_key(bat_get("voltage_entity", ""), DEV_BATTERY_VOLTAGE)
    i_eid = effective_entity_key(bat_get("current_entity", ""), DEV_BATTERY_CURRENT)
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

def _heater_enabled():
    try:
        en   = heat_get_var("enabled", None)
        heid = (heater_resolve_entity("input_heizstab_cache") or "").strip()
        wwid = (heater_resolve_entity("input_warmwasser_cache") or "").strip()
        maxp = float(heat_get_var("max_power_heater", 0.0) or 0.0)
        return bool((en is True) or (heid and wwid and maxp > 0.0))
    except Exception:
        return False

def _wallbox_enabled():
    try:
        return bool(wb_get("enabled", False))
    except Exception:
        return False


def _planner_boost_kw() -> float:
    """
    Temporary extra headroom used by the planner beyond measured surplus.
    Includes both settled ramp bonus and the currently active probe offset.
    """
    try:
        snap = get_pv_ramp_snapshot() or {}
        stable_kw = max(_num(snap.get("stable_bonus_kw"), 0.0), 0.0)
        probe_kw = max(_num(snap.get("probe_offset_kw"), 0.0), 0.0)
        candidate_kw = max(_num(snap.get("candidate_bonus_kw"), stable_kw + probe_kw), 0.0)
        return max(candidate_kw, 0.0)
    except Exception:
        return 0.0

def _battery_enabled():
    try:
        return bool(bat_get("enabled", True))
    except Exception:
        return True

def _device_from_width(w):
    try:
        w = int(w or 0)
    except Exception:
        w = 0
    if w and w < 680:   # Phone
        return "phone"
    if w and w < 1100:  # Tablet
        return "tablet"
    return "desktop"    # Default

# ------------------------------
# Sensor-Resolver
# ------------------------------
def resolve_sensor_id(kind: str) -> str:
    return resolve_runtime_sensor_id(kind, allow_mock=True)

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

def _battery_cost_per_kwh(pv_cost: float) -> float:
    """
    Kostenannahme für entladene Batterieenergie.
    Default: wie PV-Opportunitätskosten.
    Optional konfigurierbar über Settings:
      battery_cost_policy: pv | zero | fixed | sensor
      battery_cost_value: <€/kWh>        (für fixed)
      battery_cost_sensor: <entity_id>   (für sensor)
    """
    try:
        mode = (set_get("battery_cost_policy", "pv") or "pv").lower()
        if mode == "zero":
            return 0.0
        if mode == "fixed":
            return float(set_get("battery_cost_value", pv_cost) or pv_cost)
        if mode == "sensor":
            sens = set_get("battery_cost_sensor", "") or ""
            try:
                return float(get_sensor_value(sens)) if sens else pv_cost
            except Exception:
                return pv_cost
        # default: gleich wie PV
        return pv_cost
    except Exception:
        return pv_cost

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


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    color = (hex_color or "").lstrip("#")
    if len(color) != 6:
        return hex_color
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ------------------------------
# Farben
# ------------------------------
COLORS = {
    "inflow": "#FFD700",
    "pv": PV_GREEN,
    "boost": BOOST_GREEN,
    "grid": GRID_RED,
    "cooling": COOLING_BLUE,
    "miners": CONSUMER_ORANGE,
    "battery": BATTERY_PURPLE,
    "heater": HEATER_BLUE,
    "wallbox": WALLBOX_GREEN,
    "grid_feed": GRID_FEED_RED,
    "load": HOUSE_GREY,
    "inactive": INACTIVE_GREY,
}

# ------------------------------
# Callbacks
# ------------------------------
def register_callbacks(app):
    @app.callback(
        Output("frame", "data"),
        Input("pv-update", "n_intervals")
    )
    def collect_frame(_):
        # IDs einmal ermitteln
        pv_id = resolve_sensor_id("pv_production")
        grid_id = resolve_sensor_id("grid_consumption")
        feed_id = resolve_sensor_id("grid_feed_in")

        # Grundwerte lesen (einmal!)
        pv_val = float(get_sensor_value(pv_id) or 0.0)
        grid_val = float(get_sensor_value(grid_id) or 0.0)
        feed_val = float(get_sensor_value(feed_id) or 0.0)

        bat_pwr = float(_battery_power_kw_live() or 0.0)
        boost_kw = float(_planner_boost_kw() or 0.0)
        heater_kw = float(_heater_power_kw() or 0.0)
        wallbox_kw = float(_wallbox_power_kw() or 0.0)

        # Cooling (einmal!) – Feature-Flag respektieren
        cooling_enabled = bool(set_get("cooling_feature_enabled", False))

        cooling_running = False
        cooling_pkw = 0.0
        if cooling_enabled:
            try:
                c = get_cooling() or {}
                cooling_running = bool(c.get("effective_on", False))
                cooling_pkw = float(c.get("power_kw") or 0.0) if cooling_running else 0.0

            except Exception:
                cooling_running = False
                cooling_pkw = 0.0

        cooling_status = "" # fürs Label klar ermitteln
        if cooling_enabled:
            c = get_cooling() or {}
            phase = (c.get("phase") or "").strip().lower()
            if phase == "running":
                cooling_status = "Cooling running"
            elif phase == "starting":
                cooling_status = "Cooling waiting for ready…"
            elif phase == "stopping":
                cooling_status = "Cooling stopping..."
            elif phase == "running_no_state":
                cooling_status = "Cooling (no state entity) ON"
            elif phase == "start_failed":
                cooling_status = "Cooling start timeout"
            elif phase == "stop_failed":
                cooling_status = "Cooling stop timeout"
            else:
                cooling_status = "Cooling off"

        # Miners (nur das Nötigste)
        try:
            miners_raw = list_miners() or []
        except Exception:
            miners_raw = []
        miners = [{
            "name": (m.get("name") or "Miner").strip(),
            "kw": float(m.get("power_kw") or 0.0),
            "active": bool(m.get("enabled")) and bool(m.get("effective_on", m.get("on"))),
        } for m in miners_raw]

        return {
            "pv": pv_val,
            "grid": grid_val,
            "feed": feed_val,
            "bat_pwr": bat_pwr,
            "boost_kw": boost_kw,
            "heater_kw": heater_kw,
            "wallbox_kw": wallbox_kw,
            "cooling": {"enabled": cooling_enabled, "running": cooling_running, "pkw": cooling_pkw, "status": cooling_status},
            "miners": miners,
        }

    @app.callback(
        Output("sankey-diagram", "figure"),
        Input("frame", "data"),
        Input("viewport", "data"),
    )
    def update_sankey(data, viewport_w):
        if not data:
            return go.Figure()

        # which device class?
        device = _device_from_width(viewport_w)

        # dashboard flags from settings (with safe defaults)
        show_all_desktop = bool(set_get("ui_show_inactive_desktop", True))
        show_all_tablet = bool(set_get("ui_show_inactive_tablet", True))
        show_all_phone = bool(set_get("ui_show_inactive_phone", True))
        show_src_flag = bool(set_get("ui_show_inactive_sources", True))
        show_sink_flag = bool(set_get("ui_show_inactive_sinks", True))

        if device == "desktop":
            show_all = show_all_desktop
        elif device == "tablet":
            show_all = show_all_tablet
        else:
            show_all = show_all_phone

        # final ghost toggles
        SHOW_GHOST_SRC = show_all and show_src_flag
        SHOW_GHOST_SINK = show_all and show_sink_flag

        # feature enabled?
        battery_feat = _battery_enabled()
        heater_feat = _heater_enabled()
        wallbox_feat = _wallbox_enabled()
        # cooling feature kommt schon aus deinem Snapshot: cooling_feature

        # --- Werte aus dem Snapshot ---
        pv_val = data["pv"]
        grid_val = data["grid"]
        feed_val = data["feed"]
        bat_pwr = data["bat_pwr"]
        boost_kw = max(float(data.get("boost_kw", 0.0) or 0.0), 0.0)
        heater_kw = data["heater_kw"]
        wallbox_kw = data["wallbox_kw"]

        cooling_info = data.get("cooling", {})
        cooling_feature = bool(cooling_info.get("enabled", False))
        cooling_kw = float(cooling_info.get("pkw", 0.0)) if cooling_info.get("running") else 0.0

        miners_in = data.get("miners", [])
        miner_entries = []
        sum_active_miners_kw = 0.0
        for m in miners_in:
            mid = (m.get("id") or m.get("name") or "").strip()
            # label override from settings_store
            disp = set_get(f"miner.{mid}.label", None)
            name = (disp if (disp is not None and str(disp).strip()) else m["name"]).strip()

            if m["active"]:
                miner_entries.append({"name": name, "kw": max(m["kw"], 0.0),
                                      "color": COLORS["miners"], "ghost": False})
                sum_active_miners_kw += max(m["kw"], 0.0)
            elif SHOW_GHOST_SINK:
                miner_entries.append({"name": name, "kw": GHOST_KW,
                                      "color": COLORS["inactive"], "ghost": True})

        # --- Batterie: + = Laden (Senke), - = Entladen (Quelle) ---
        bat_charge_kw = max(bat_pwr, 0.0)  # Senke
        bat_discharge_kw = max(-bat_pwr, 0.0)  # Quelle

        # Verfügbare Energie für Verbraucher = PV + Ramp-Boost + Grid (+ Entladung)
        inflow_base = max(pv_val + boost_kw + grid_val, 0.0)
        inflow_eff = inflow_base + bat_discharge_kw

        # ---- Prozentanteile für den Inflow-Knoten ----
        den = inflow_eff if inflow_eff > 0 else 0.0
        pv_pct = round((pv_val / den) * 100.0, 1) if den else 0.0
        boost_pct = round((boost_kw / den) * 100.0, 1) if den else 0.0
        grid_pct = round((grid_val / den) * 100.0, 1) if den else 0.0
        batt_pct = round((bat_discharge_kw / den) * 100.0, 1) if den else 0.0

        # ---- Weitere Lasten (Heater/Wallbox) ----
        heater_kw = _heater_power_kw()
        wallbox_kw = _wallbox_power_kw()

        # ---- House usage = Rest (ohne Ghosts) ----
        # WICHTIG: feed_val und bat_charge_kw sind echte Outflows und werden hier abgezogen
        known_real = (
                sum_active_miners_kw
                + max(feed_val, 0.0)
                + heater_kw + wallbox_kw + cooling_kw
                + bat_charge_kw
        )
        house_kw = max(inflow_eff - known_real, 0.0)

        # === NEW: Outflows auf Inflow kappen (proportional skalieren) ===
        EPS = 0.02  # ~20 W Rauschtoleranz
        requested = (
                sum_active_miners_kw
                + heater_kw + wallbox_kw + cooling_kw
                + bat_charge_kw + max(feed_val, 0.0)
        )

        if requested > inflow_eff + EPS:
            scale = (inflow_eff / requested) if requested > 0 else 0.0

            for me in miner_entries:
                if not me.get("ghost"):
                    me["kw"] *= scale

            heater_kw *= scale
            wallbox_kw *= scale
            cooling_kw *= scale
            bat_charge_kw *= scale
            feed_val *= scale  # wichtig: skaliert den gezeichneten Feed-in

            house_kw = 0.0
        # === END NEW ===

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
            link_color.append(_hex_to_rgba(color, 0.92) if color != COLORS["inactive"] else _hex_to_rgba(color, 0.45))

        # Node-Label leer lassen; Text zeigen wir als Annotation oben mittig.
        inflow_line1 = f"Energy Inflow — {_fmt_kw(inflow_eff)}"
        inflow_line2 = f"PV: {pv_pct}% · Boost: {boost_pct}% · Grid: {grid_pct}% · Battery: {batt_pct}%"
        inflow_idx = add_node(" ", COLORS["inflow"])

        # ---------- Linke Quellknoten (optional) ----------
        pv_src_idx = None
        if (pv_val > 0.0) or (SHOW_GHOST_SRC):
            pv_active = pv_val > 0.0
            pv_color = COLORS["pv"] if pv_active else COLORS["inactive"]
            pv_eff = pv_val if pv_active else (GHOST_KW if SHOW_GHOST_SRC else 0.0)
            if pv_active or SHOW_GHOST_SRC:
                pv_src_idx = add_node(f"PV source<br>{_fmt_kw(pv_val)}", pv_color)
                add_link(pv_src_idx, inflow_idx, pv_eff, pv_color)

        grid_src_idx = None
        if (grid_val > 0.0) or (SHOW_GHOST_SRC):
            grid_active = grid_val > 0.0
            grid_color = COLORS["grid"] if grid_active else COLORS["inactive"]
            grid_eff = grid_val if grid_active else (GHOST_KW if SHOW_GHOST_SRC else 0.0)
            if grid_active or SHOW_GHOST_SRC:
                grid_src_idx = add_node(f"Grid (import)<br>{_fmt_kw(grid_val)}", grid_color)
                add_link(grid_src_idx, inflow_idx, grid_eff, grid_color)

        if boost_kw > 0.0:
            boost_idx = add_node(f"PV ramp-up reserve<br>{_fmt_kw(boost_kw)}", COLORS["boost"])
            add_link(boost_idx, inflow_idx, boost_kw, COLORS["boost"])

        battery_src_idx = None
        if battery_feat and ((bat_discharge_kw > 0.0) or SHOW_GHOST_SRC):
            bat_active = bat_discharge_kw > 0.0
            bat_color = COLORS["battery"] if bat_active else COLORS["inactive"]
            bat_eff = bat_discharge_kw if bat_active else (GHOST_KW if SHOW_GHOST_SRC else 0.0)
            if bat_active or SHOW_GHOST_SRC:
                battery_src_idx = add_node(f"Battery (discharge)<br>{_fmt_kw(bat_discharge_kw)}", bat_color)
                add_link(battery_src_idx, inflow_idx, bat_eff, bat_color)


        # ---------- Verbraucher/Senken rechts ----------
        # ---- Cooling zeichnen (einmal) ----
        if cooling_feature:
            cooling_is_active = cooling_kw > 0.0
            cooling_kw_eff = cooling_kw if cooling_is_active else (GHOST_KW if SHOW_GHOST_SINK else 0.0)
            if cooling_is_active or SHOW_GHOST_SINK:
                cooling_color = COLORS["cooling"] if cooling_is_active else COLORS["inactive"]
                cooling_idx = add_node(f"Cooling circuit<br>{_fmt_kw(cooling_kw)}", cooling_color)
                add_link(inflow_idx, cooling_idx, cooling_kw_eff, cooling_color)

        # Miner
        for me in miner_entries:
            idx = add_node(f"{me['name']}<br>{_fmt_kw(me['kw'])}", me["color"])
            add_link(inflow_idx, idx, me["kw"], me["color"])

        # Heater
        heater_is_active = heater_kw > 0.0
        if heater_is_active or SHOW_GHOST_SINK:
            heater_color = COLORS.get("heater", "#3399FF") if heater_is_active else COLORS.get("inactive", "#DDDDDD")
            heater_idx = add_node(f"Water Heater<br>{_fmt_kw(heater_kw)}", heater_color)
            add_link(inflow_idx, heater_idx, heater_kw if heater_is_active else GHOST_KW, heater_color)

        # Wallbox
        wallbox_is_active = wallbox_kw > 0.0
        if wallbox_is_active or SHOW_GHOST_SINK:
            wallbox_color = COLORS.get("wallbox", "#33CC66") if wallbox_is_active else COLORS.get("inactive", "#DDDDDD")
            wallbox_idx = add_node(f"Wallbox<br>{_fmt_kw(wallbox_kw)}", wallbox_color)
            add_link(inflow_idx, wallbox_idx, wallbox_kw if wallbox_is_active else GHOST_KW, wallbox_color)

        # Battery (charge)
        if bat_charge_kw > 0.0 or SHOW_GHOST_SINK:
            is_active = bat_charge_kw > 0.0
            bat_color2 = COLORS.get("battery", "#8E44AD") if is_active else COLORS.get("inactive", "#DDDDDD")
            bat_sink = add_node(f"Battery (charge)<br>{_fmt_kw(bat_charge_kw)}", bat_color2)
            add_link(inflow_idx, bat_sink, bat_charge_kw if is_active else GHOST_KW, bat_color2)

        # Grid Feed-in
        feed_is_active = feed_val > 0.0
        if feed_is_active or SHOW_GHOST_SINK:
            feed_color = COLORS.get("grid_feed", "#FF3333") if feed_is_active else COLORS.get("inactive", "#DDDDDD")
            feed_idx = add_node(f"Grid Feed-in<br>{_fmt_kw(feed_val)}", feed_color)
            add_link(inflow_idx, feed_idx, feed_val if feed_is_active else GHOST_KW, feed_color)

        # House usage (kein Ghost)
        house_idx = add_node(f"House usage<br>{_fmt_kw(house_kw)}", COLORS.get("load", "#A0A0A0"))
        add_link(inflow_idx, house_idx, house_kw, COLORS.get("load", "#A0A0A0"))

        # Figure
        fig = go.Figure(data=[go.Sankey(
            valueformat=".3f",
            valuesuffix=" kW",
            node=dict(
                label=node_labels,
                pad=30, thickness=25,
                line=dict(color=PLOT_LINE, width=0.6),
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
            font=dict(size=14, color=TEXT_PRIMARY),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=100, b=20) #Top Margin ist der abstand darüber!
        )
        fig.update_traces(hoverlabel=dict(bgcolor="#111724", font=dict(color=TEXT_PRIMARY)))

        # 1. Zeile: Energy Inflow — kW
        fig.add_annotation(
            x=0.5, y=1.09, xref="paper", yref="paper",
            xanchor="center", yanchor="bottom",
            # text=f"<b>{inflow_line1}</b>",
            text=inflow_line1,
            showarrow=False, align="center",
            font=dict(size=13, color=TEXT_PRIMARY),
            bgcolor="rgba(0,0,0,0)"
        )

        # 2. Zeile: PV %, Grid %, Battery %
        fig.add_annotation(
            x=0.5, y=1.045, xref="paper", yref="paper",
            xanchor="center", yanchor="bottom",
            text=inflow_line2,
            showarrow=False, align="center",
            font=dict(size=13, color=TEXT_MUTED),
            bgcolor="rgba(0,0,0,0)"
        )

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
                        {"range": [0, axis_max / 2], "color": _hex_to_rgba(color, 0.14)},
                        {"range": [axis_max / 2, axis_max], "color": _hex_to_rgba(color, 0.24)},
                    ],
                    "borderwidth": 0,
                }
            ))
            fig.update_layout(**GAUGE_LAYOUT)
            return fig

        return (
            build_gauge(pv_val, "PV production (kW)", PV_GREEN),
            build_gauge(grid_val, "Grid consumption (kW)", GRID_RED),
            build_gauge(feed_val, "Grid feed-in (kW)", GRID_FEED_RED),
        )

    @app.callback(
        Output("battery-gauge", "figure"),
        Input("pv-update", "n_intervals"),
    )
    def update_battery(_n):
        # SOC (%) und Leistung (kW) ermitteln
        soc = _battery_soc_percent()  # kann None sein
        pkw = _battery_power_kw_live()

        # Skala = Kapazität in kWh
        cap = _battery_capacity_kwh()
        axis_max = cap

        # Wert in kWh aus SOC
        if soc is None:
            value_kwh = 0.0
        else:
            value_kwh = max(0.0, min(cap * (float(soc) / 100.0), cap))

        bar_color = BATTERY_PURPLE

        # Ticks 0 – ½ – max
        ticks = [0.0, axis_max / 2.0, axis_max]

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=value_kwh,
            number=GAUGE_NUMBER_FONT | {"valueformat": ".2f"},
            title={"text": "Battery energy (kWh)", **GAUGE_TITLE_FONT},
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
                    {"range": [0, axis_max / 2], "color": _hex_to_rgba(BATTERY_PURPLE, 0.14)},
                    {"range": [axis_max / 2, axis_max], "color": _hex_to_rgba(BATTERY_PURPLE, 0.24)},
                ],
                "borderwidth": 0,
            },
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
        price = get_virtual_value(VIRTUAL_BTC_PRICE, entities.get("sensor_btc_price"))
        hashrate = get_virtual_value(VIRTUAL_BTC_HASHRATE, entities.get("sensor_btc_hashrate"))

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

        # --- 2) Net load cost adjusted (PV + Battery + Grid) ---
        try:
            pv_id = resolve_sensor_id("pv_production")
            grid_id = resolve_sensor_id("grid_consumption")

            pv_val = max(float(get_sensor_value(pv_id) or 0.0), 0.0)
            grid_val = max(float(get_sensor_value(grid_id) or 0.0), 0.0)

            # Batterie-Entladung in kW (nur >0 zählt als Quelle)
            bat_pwr = float(_battery_power_kw_live() or 0.0)
            bat_discharge = max(-bat_pwr, 0.0)

            denom = pv_val + grid_val + bat_discharge
            if denom > 0.0:
                pv_share = pv_val / denom
                grid_share = grid_val / denom
                bat_share = bat_discharge / denom
            else:
                pv_share = grid_share = bat_share = 0.0

            pv_cost = _pv_cost_per_kwh()
            bat_cost = _battery_cost_per_kwh(pv_cost)

            blended = pv_share * pv_cost + bat_share * bat_cost + grid_share * market
            blended_color = _price_color_blended(blended)
            blended_txt = f"Net load cost adjusted: {_fmt_price(blended)} {sym}/kWh"
            blended_out = html.Span([_dot(blended_color, "1em"), blended_txt])
        except Exception:
            blended_out = html.Span([_dot("#888", "1em"), "Net load cost adjusted: –"])

        return market_out, blended_out

    @app.callback(
        Output("dashboard-water-temp", "children"),
        Input("pv-update", "n_intervals")  # alle 10s
    )
    def update_dashboard_water_temp(_):
        entity_id = effective_entity_key(heater_resolve_entity("input_warmwasser_cache"), DEV_HEATER_WATER_TEMP)
        if not entity_id:
            return html.Span([_icon("temp"), "Water Temp: –"])
        val = get_sensor_value(entity_id)
        unit = heat_get_var("heat_unit", "°C")
        return html.Span([_icon("temp"), f"Water Temp: {_fmt_temp(val, unit)}"])

    # liefert die Fensterbreite (Desktop/Tablet/Phone-Erkennung)
    app.clientside_callback(
        """
        function(n){
            return (typeof window !== 'undefined' && window.innerWidth)
                ? window.innerWidth
                : 1400;  // Fallback
        }
        """,
        Output("viewport", "data"),
        Input("pv-update", "n_intervals")
    )


# ------------------------------
# Layout
# ------------------------------
def layout():
    return page_wrap([
        dcc.Store(id="frame", storage_type="memory"),
        dcc.Store(id="viewport", storage_type="memory"),
        html.H2("Current Power Allocation", className="dashboard-heading"),
        html.Div(
            dcc.Graph(
                id="sankey-diagram",
                figure=go.Figure(),
                className="dashboard-graph dashboard-sankey",
                config={"displayModeBar": False},
            ),
            className="dashboard-sankey-zone",
        ),

        html.Div([
            dcc.Graph(id="pv-gauge",
                      className="dashboard-graph dashboard-gauge",
                      style={"minWidth": "300px", "height": "300px"},
                      config={"displayModeBar": False}),
            dcc.Graph(id="grid-gauge",
                      className="dashboard-graph dashboard-gauge",
                      style={"minWidth": "300px", "height": "300px"},
                      config={"displayModeBar": False}),
            dcc.Graph(id="feed-gauge",
                      className="dashboard-graph dashboard-gauge",
                      style={"minWidth": "300px", "height": "300px"},
                      config={"displayModeBar": False}),
            dcc.Graph(id="battery-gauge",
                      className="dashboard-graph dashboard-gauge",
                      style={"minWidth": "300px", "height": "300px"},
                      config={"displayModeBar": False}),
        ], className="dashboard-gauge-grid"),

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

