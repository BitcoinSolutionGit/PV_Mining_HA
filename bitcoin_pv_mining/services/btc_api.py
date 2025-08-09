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
    "mempool_space": 20
}

API_URLS = {
    "coingecko": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
    "coinbase": "https://api.coinbase.com/v2/prices/spot?currency=USD",
    "blockchain_info": "https://api.blockchain.info/stats",
    "mempool_space": "https://mempool.space/api/v1/mining/hashrate/3d"
}

LAST_UPDATE = {
    "coingecko": 0,
    "coinbase": 0,
    "blockchain_info": 0,
    "mempool_space": 0
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

def convert_blockchain_info_hashrate_to_th(raw_hashrate):
    try:
        # Convert from GH/s to TH/s (1 TH/s = 1e3 GH/s)
        exahash = float(raw_hashrate) / 1e3
        return round(exahash, 2)
    except:
        return None

def convert_mempool_space_hashrate_to_th(raw_hs):
    try:
        return round(float(raw_hs) / 1e12, 2)  # H/s -> TH/s
    except:
        return None

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
                    entities["sensor_btc_hashrate"] = convert_blockchain_info_hashrate_to_th(hashrate)
                    LAST_UPDATE["blockchain_info"] = now
                    updated = True

            elif now - LAST_UPDATE["mempool_space"] >= INTERVALS_MINUTES["mempool_space"] * 60:
                hashrate = get_btc_hashrate_from_mempool_space()
                if hashrate is not None:
                    entities["sensor_btc_hashrate"] = convert_mempool_space_hashrate_to_th(hashrate)
                    LAST_UPDATE["mempool_space"] = now
                    updated = True

            if updated:
                save_entities(CONFIG_PATH, entities)
                # print("[BTC] Updated BTC info:", entities)

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

def get_btc_hashrate_from_mempool_space():
    try:
        r = requests.get(API_URLS["mempool_space"], timeout=5)
        if r.status_code == 200:
            data = r.json()
            current_hashrate = data.get("currentHashrate")
            if current_hashrate:
                return float(current_hashrate)  # Wert in H/s
    except:
        return None