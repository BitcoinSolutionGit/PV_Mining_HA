import os
import threading
import time
import yaml
import requests

CONFIG_DIR = "/config/pv_mining_addon"
CONFIG_PATH = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

INTERVALS_MINUTES = {
    "coingecko": 5,
    "coinbase": 10,
    "blockchain_info": 15,
    "blockchain_com": 20
}

API_URLS = {
    "coingecko": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
    "coinbase": "https://api.coinbase.com/v2/prices/spot?currency=USD",
    "blockchain_info": "https://api.blockchain.info/stats",
    "blockchain_com": "https://api.blockchain.com/charts/hash-rate?timespan=1days&format=json"
}

LAST_UPDATE = {
    "coingecko": 0,
    "coinbase": 0,
    "blockchain_info": 0,
    "blockchain_com": 0
}

def load_config(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except:
        return {}

def save_entities(CONFIG_PATH, entities):
    config = load_config(CONFIG_PATH)
    config["entities"] = entities
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f)

def update_btc_data_periodically(CONFIG_PATH):
    def updater():
        while True:
            config = load_config(CONFIG_PATH)
            entities = config.get("entities", {})
            now = time.time()
            updated = False

            if now - LAST_UPDATE["coingecko"] >= INTERVALS_MINUTES["coingecko"] * 60:
                price = get_btc_price_from_coingecko()
                if price is not None:
                    entities["sensor_btc_price"] = price
                    LAST_UPDATE["coingecko"] = now
                    updated = True

            elif now - LAST_UPDATE["coinbase"] >= INTERVALS_MINUTES["coinbase"] * 60:
                price = get_btc_price_from_coinbase()
                if price is not None:
                    entities["sensor_btc_price"] = price
                    LAST_UPDATE["coinbase"] = now
                    updated = True

            if now - LAST_UPDATE["blockchain_info"] >= INTERVALS_MINUTES["blockchain_info"] * 60:
                hashrate = get_btc_hashrate_from_blockchain_info()
                if hashrate is not None:
                    entities["sensor_btc_hashrate"] = hashrate
                    LAST_UPDATE["blockchain_info"] = now
                    updated = True

            elif now - LAST_UPDATE["blockchain_com"] >= INTERVALS_MINUTES["blockchain_com"] * 60:
                hashrate = get_btc_hashrate_from_blockchain_com()
                if hashrate is not None:
                    entities["sensor_btc_hashrate"] = hashrate
                    LAST_UPDATE["blockchain_com"] = now
                    updated = True

            if updated:
                save_entities(CONFIG_PATH, entities)
                print("[BTC] Updated BTC info:", entities)

            time.sleep(30)

    threading.Thread(target=updater, daemon=True).start()

def get_btc_price_from_coingecko():
    try:
        r = requests.get(API_URLS["coingecko"], timeout=5)
        if r.status_code == 200:
            return r.json()["bitcoin"]["usd"]
    except:
        pass
    return None

def get_btc_price_from_coinbase():
    try:
        r = requests.get(API_URLS["coinbase"], timeout=5)
        if r.status_code == 200:
            return float(r.json()["data"]["amount"])
    except:
        pass
    return None

def get_btc_hashrate_from_blockchain_info():
    try:
        r = requests.get(API_URLS["blockchain_info"], timeout=5)
        if r.status_code == 200:
            return r.json().get("hash_rate", None)
    except:
        pass
    return None

def get_btc_hashrate_from_blockchain_com():
    try:
        r = requests.get(API_URLS["blockchain_com"], timeout=5)
        if r.status_code == 200:
            values = r.json().get("values", [])
            if values:
                return values[-1]["y"]
    except:
        pass
    return None