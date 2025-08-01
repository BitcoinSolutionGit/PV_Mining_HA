# Rentabilitätsberechnungen
def calc_miner_profitability(hashrate_th, verbrauch_kwh, btc_price_eur, kest, stromkosten):
    daily_income = hashrate_th * 0.000008 * btc_price_eur
    daily_cost = verbrauch_kwh * 24 * stromkosten
    return (daily_income * (1 - kest)) - daily_cost

def prozentwert_fuer_leistung(max_leistung_kwh, verfuegbar_kw):
    return min(100, int((verfuegbar_kw / max_leistung_kwh) * 100))
