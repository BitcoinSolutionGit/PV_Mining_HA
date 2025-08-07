# /config/pv_mining_addon/btc_api_tests.py

from btc_api import (
    get_btc_price_from_coingecko,
    get_btc_price_from_coinbase,
    get_btc_hashrate_from_blockchain_info,
    get_btc_hashrate_from_blockchain_com,
    convert_blockchain_info_hashrate_to_th,
    convert_blockchain_com_hashrate_to_th
)

def run_all_tests():
    print("\n=== BTC API LIVE TEST ===\n")

    # Preisquellen
    print("→ Preisquellen:")
    cg_price = get_btc_price_from_coingecko()
    print(f"  CoinGecko:       {cg_price} USD" if cg_price else "  CoinGecko:       ❌ Fehler oder keine Antwort")

    cb_price = get_btc_price_from_coinbase()
    print(f"  Coinbase:        {cb_price} USD" if cb_price else "  Coinbase:        ❌ Fehler oder keine Antwort")

    # Hashratequellen
    print("\n→ Hashratequellen:")
    bc_info = get_btc_hashrate_from_blockchain_info()
    bc_info_th = convert_blockchain_info_hashrate_to_th(bc_info) if bc_info else None
    print(f"  Blockchain.info: {bc_info_th} TH/s" if bc_info_th else "  Blockchain.info: ❌ Fehler oder keine Antwort")

    bc_com = get_btc_hashrate_from_blockchain_com()
    bc_com_th = convert_blockchain_com_hashrate_to_th(bc_com) if bc_com else None
    print(f"  Blockchain.com:  {bc_com_th} TH/s" if bc_com_th else "  Blockchain.com:  ❌ Fehler oder keine Antwort")

    print("\n=== Ende der Tests ===\n")

if __name__ == "__main__":
    run_all_tests()

    #aufgerufen wird das über den hopme assistant terminal mit diesem zweizeiligen befehl:
    #cd /config/pv_mining_addon # einmalig, um ins Add-on-Verzeichnis zu wechseln
    #python3 btc_api_tests.py # führt den Test aus

