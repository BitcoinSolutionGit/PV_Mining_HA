# zentrale Logik
import time
import json
from btc_api import get_btc_price
from utils import calc_miner_profitability, prozentwert_fuer_leistung

CONFIG = json.load(open("config.json"))
SENSORS = CONFIG["sensor_mapping"]
AKTOREN = CONFIG["aktor_mapping"]
FLAGS = CONFIG["feature_flags"]

def steuerungsschleife():
    while True:
        pv = hass.states.get(SENSORS["pv_erzeugung"]).state
        verbrauch = hass.states.get(SENSORS["aktueller_verbrauch"]).state
        ueberschuss = float(pv) - float(verbrauch)

        btc_price = get_btc_price()

        miner_profits = []
        for i in range(1, CONFIG["miner_count"] + 1):
            conf = CONFIG[f"miner_{i}"]
            profit = calc_miner_profitability(
                conf["hashrate"], conf["verbrauch_kwh"], btc_price,
                CONFIG["btc_kest"], CONFIG["stromkosten_eur"])
            miner_profits.append((i, profit, conf["verbrauch_kwh"]))

        miner_profits.sort(key=lambda x: x[1], reverse=True)

        for m_id, profit, kwh in miner_profits:
            if profit > 0 and ueberschuss >= kwh:
                hass.services.call("script", f"bitcoin_miner{m_id}_ein")
                ueberschuss -= kwh
                break

        temp = float(hass.states.get(SENSORS["wassertemperatur"]).state)

        if FLAGS.get("heizstab_aktiv") and ueberschuss > 0 and temp < 60:
            prozent = prozentwert_fuer_leistung(CONFIG["heizstab_max_kwh"], ueberschuss)
            hass.states.set(AKTOREN["heizstab_prozent"], prozent)
            ueberschuss -= (prozent / 100.0) * CONFIG["heizstab_max_kwh"]
        elif FLAGS.get("heizstab_aktiv"):
            hass.states.set(AKTOREN["heizstab_prozent"], 0)

        if FLAGS.get("wallbox_aktiv") and ueberschuss > 0:
            prozent = prozentwert_fuer_leistung(CONFIG["autobatt_max_ladeleistung"], ueberschuss)
            hass.states.set(AKTOREN["wallbox_prozent"], prozent)
            ueberschuss -= (prozent / 100.0) * CONFIG["autobatt_max_ladeleistung"]

        if FLAGS.get("hausbatterie_aktiv") and ueberschuss > 0:
            prozent = prozentwert_fuer_leistung(CONFIG["hausbatt_max_ladeleistung"], ueberschuss)
            hass.states.set(AKTOREN["hausbatterie_prozent"], prozent)

        time.sleep(60)