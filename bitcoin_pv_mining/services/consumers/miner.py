import os
from .base import Desire

from services.miners_store import list_miners
from services.settings_store import get_var as set_get
from services.electricity_store import current_price as elec_price, get_var as elec_get
from services.ha_sensors import get_sensor_value
from services.cooling_store import get_cooling
from services.utils import load_yaml
from services.btc_metrics import get_live_btc_price_eur, get_live_network_hashrate_ths, sats_per_th_per_hour

CONFIG_DIR = "/config/pv_mining_addon"
SENS_DEF = os.path.join(CONFIG_DIR, "sensors.yaml")
SENS_OVR = os.path.join(CONFIG_DIR, "sensors.local.yaml")


def _map(key: str) -> str:
    def _mget(path, k):
        try:
            m = (load_yaml(path, {}).get("mapping", {}) or {})
        except Exception:
            m = {}
        return (m.get(k) or "").strip()
    return _mget(SENS_OVR, key) or _mget(SENS_DEF, key)

def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

# kleine Kopie deiner Profit-Logik (vereinfacht)

def _is_profitable(m: dict, cooling_kw_if_needed: float, cooling_running_now: bool) -> tuple[bool, str]:
    ths = _num(m.get("hashrate_ths"), 0.0)
    pkw = _num(m.get("power_kw"), 0.0)
    if ths <= 0.0 or pkw <= 0.0:
        return False, "no hashrate/power"

    btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
    net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
    reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
    tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

    sat_th_h = sats_per_th_per_hour(reward, net_ths)
    sats_per_h = sat_th_h * ths
    eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
    revenue_eur_h = sats_per_h * eur_per_sat
    after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct/100.0, 1.0)))

    pv_id=_map("pv_production"); grid_id=_map("grid_consumption"); feed_id=_map("grid_feed_in")
    pv=_num(get_sensor_value(pv_id),0.0); grid=_num(get_sensor_value(grid_id),0.0); feed=max(_num(get_sensor_value(feed_id),0.0),0.0)

    base = elec_price() or 0.0
    fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)

    # PV-Kosten-Policy
    policy = (set_get("pv_cost_policy","zero") or "zero").lower()
    if policy == "feedin":
        mode = (set_get("feedin_price_mode","fixed") or "fixed").lower()
        fee_up = _num(elec_get("network_fee_up_value", 0.0), 0.0)
        if mode == "sensor":
            sens = set_get("feedin_price_sensor","") or ""
            tarif=_num(get_sensor_value(sens) if sens else 0.0,0.0)
        else:
            tarif=_num(set_get("feedin_price_value",0.0),0.0)
        pv_cost=max(tarif-fee_up,0.0)
    else:
        pv_cost=0.0

    # ΔP enthält Cooling, falls benötigt & noch nicht läuft
    delta_kw = pkw + (0.0 if cooling_running_now else cooling_kw_if_needed)

    pv_share_add = max(min(feed / max(delta_kw, 1e-9), 1.0), 0.0) if delta_kw>0 else 0.0
    grid_share_add = 1.0 - pv_share_add
    blended = pv_share_add*pv_cost + grid_share_add*(base + fee_down)

    # fairer Cooling-Anteil (einfach +konservativ)
    cool_share = 0.0
    if cooling_kw_if_needed>0 and not cooling_running_now and bool(m.get("require_cooling")):
        cool_share = cooling_kw_if_needed * blended  # konservativ

    cost = pkw*blended + cool_share
    ok = (after_tax - cost) > 0.0
    why = f"rev={after_tax:.3f}€/h cost={cost:.3f}€/h (ΔP={delta_kw:.2f}kW)"
    return ok, why

def desires_for_all_miners(cooling_running_now: bool, cooling_kw_cfg: float):
    """Erzeugt pro Miner (id) einen Desire-Eintrag: ('miner:<id>', Desire, miner_dict)"""
    out = []
    for i, m in enumerate(list_miners() or []):
        if not m.get("enabled"):
            continue
        auto = (str(m.get("mode") or "").lower()=="auto")
        if not auto:
            continue
        require_cooling = bool(m.get("require_cooling"))
        cool_kw = cooling_kw_cfg if require_cooling else 0.0
        profitable, why = _is_profitable(m, cool_kw, cooling_running_now)
        pkw = _num(m.get("power_kw"), 0.0)
        wants = profitable
        desire = Desire(
            wants=wants,
            min_kw=0.0,
            max_kw=pkw if wants else 0.0,
            must_run=False,
            exact_kw=pkw if wants else None,
            reason=("profitable" if wants else "not profitable") + f" · {why}"
        )
        out.append( (f"miner:{m['id']}", desire, m) )
    return out

# --- append at end of services/consumers/miner.py ---
def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d

def _load_yaml(path, default):
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except Exception:
        return default

def _dash_resolve(kind: str) -> str:
    def _mget(path, key):
        m = (_load_yaml(path, {}) or {}).get("mapping", {}) or {}
        return (m.get(key) or "").strip()
    return _mget(SENS_OVR, kind) or _mget(SENS_DEF, kind)

def _pv_cost_per_kwh():
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
    # falls jemand Cent/kWh einträgt
    if 3.0 <= tarif < 1000.0:
        tarif /= 100.0
    return max(tarif - fee_up, 0.0)

class MinerConsumer:
    """
    Einzelner Miner als Consumer. Instanziiere mit der reinen Miner-ID (ohne 'miner:').
    """
    def __init__(self, miner_id: str) -> None:
        self.miner_id = miner_id

    @property
    def id(self) -> str:
        return f"miner:{self.miner_id}"

    @property
    def label(self) -> str:
        m = next((x for x in (list_miners() or []) if x.get("id") == self.miner_id), None)
        return (m.get("name") if m else None) or "Miner"

    def desire_now(self) -> Desire:
        m = next((x for x in (list_miners() or []) if x.get("id") == self.miner_id), None)
        if not m:
            return Desire(False, 0.0, 0.0, False, None, "miner not found")

        if not m.get("enabled", True):
            return Desire(False, 0.0, 0.0, False, None, "disabled")
        if (str(m.get("mode") or "").lower() != "auto"):
            return Desire(False, 0.0, 0.0, False, None, "not in auto")

        ths = _num(m.get("hashrate_ths"), 0.0)
        pkw = _num(m.get("power_kw"), 0.0)
        if ths <= 0.0 or pkw <= 0.0:
            return Desire(False, 0.0, 0.0, False, None, "incomplete config")

        # Einnahmen-Seite
        btc_eur = get_live_btc_price_eur(fallback=_num(set_get("btc_price_eur", 0.0)))
        net_ths = get_live_network_hashrate_ths(fallback=_num(set_get("network_hashrate_ths", 0.0)))
        reward  = _num(set_get("block_reward_btc", 3.125), 3.125)
        tax_pct = _num(set_get("sell_tax_percent", 0.0), 0.0)

        sat_th_h = sats_per_th_per_hour(reward, net_ths)
        sats_per_h = sat_th_h * ths
        eur_per_sat = (btc_eur / 1e8) if btc_eur > 0 else 0.0
        revenue_eur_h = sats_per_h * eur_per_sat
        after_tax = revenue_eur_h * (1.0 - max(0.0, min(tax_pct / 100.0, 1.0)))

        # Kosten-Seite (inkrementeller Mix inkl. evtl. Cooling-Start)
        pv_id   = _dash_resolve("pv_production")
        grid_id = _dash_resolve("grid_consumption")
        feed_id = _dash_resolve("grid_feed_in")
        pv_val   = _num(get_sensor_value(pv_id), 0.0)
        grid_val = _num(get_sensor_value(grid_id), 0.0)
        feed_val = max(_num(get_sensor_value(feed_id), 0.0), 0.0)

        base = elec_price() or 0.0
        fee_down = _num(elec_get("network_fee_down_value", 0.0), 0.0)
        pv_cost = _pv_cost_per_kwh()

        cooling_feature = bool(set_get("cooling_feature_enabled", False))
        require_cooling = bool(m.get("require_cooling"))
        cooling = get_cooling() if cooling_feature else {}
        cooling_kw_cfg = _num((cooling or {}).get("power_kw"), 0.0)
        cooling_is_on  = bool((cooling or {}).get("on"))

        delta_kw = pkw + (cooling_kw_cfg if (cooling_feature and require_cooling and not cooling_is_on) else 0.0)

        if delta_kw > 0.0:
            pv_share_add = max(min(feed_val / delta_kw, 1.0), 0.0)
        else:
            pv_share_add = 0.0
        grid_share_add = 1.0 - pv_share_add

        blended_eur_per_kwh = pv_share_add * pv_cost + grid_share_add * (base + fee_down)

        cool_share = 0.0
        if cooling_feature and require_cooling and cooling_kw_cfg > 0.0:
            active = [mx for mx in (list_miners() or [])
                      if mx.get("enabled") and mx.get("on") and mx.get("require_cooling")]
            n_future = len(active) + 1
            cool_share = (cooling_kw_cfg * blended_eur_per_kwh) / max(n_future, 1)

        cost_eur_h = pkw * blended_eur_per_kwh
        total_cost_h = cost_eur_h + cool_share
        profit = after_tax - total_cost_h

        if profit > 0.0:
            return Desire(
                True,
                pkw,  # min
                pkw,  # max
                False,
                pkw,  # exact: Miner ist diskret
                f"profitable (Δ={profit:.2f} €/h)"
            )
        else:
            return Desire(False, 0.0, 0.0, False, None, f"not profitable (Δ={profit:.2f} €/h)")
