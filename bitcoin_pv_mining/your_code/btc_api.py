# BTC-Preis- & Hashrate-Abfrage
import requests

def get_btc_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur"
    response = requests.get(url)
    return response.json().get("bitcoin", {}).get("eur", 0)