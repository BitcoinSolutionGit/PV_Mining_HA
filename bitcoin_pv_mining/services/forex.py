# services/forex.py
import time, requests

_CACHE = {"rate": None, "ts": 0}
_DEFAULT_TTL = 60 * 60  # 1h cache

def usd_to_eur_rate(fallback=0.93, ttl=_DEFAULT_TTL) -> float:
    """Holt USD→EUR von einer Free-API, cached 1h, fällt sauber zurück."""
    now = time.time()
    if _CACHE["rate"] and now - _CACHE["ts"] < ttl:
        return _CACHE["rate"]

    urls = [
        "https://api.frankfurter.app/latest?from=USD&to=EUR",
        "https://api.exchangerate.host/latest?base=USD&symbols=EUR",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json() or {}
                rate = float((data.get("rates", {}) or {}).get("EUR", 0)) or 0.0
                if rate > 0:
                    _CACHE.update(rate=rate, ts=now)
                    return rate
        except Exception as e:
            print(f"[forex] fetch failed: {url} -> {e}", flush=True)

    return float(fallback or 0.93)
