# services/consumers/house.py
from __future__ import annotations

import os
from services.consumers.base import BaseConsumer, Desire, Ctx
from services.ha_sensors import get_sensor_value
from services.sensor_mapping import resolve_sensor_id as resolve_runtime_sensor_id


def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _kw(v: float) -> float:
    # Heuristik: Wenn absoluter Wert > 2000, nehmen wir W an -> /1000
    try:
        f = float(v)
    except Exception:
        return 0.0
    return f / 1000.0 if abs(f) > 2000 else f


def _map(key: str) -> str:
    return resolve_runtime_sensor_id(key, allow_mock=True)


class HouseLoadConsumer(BaseConsumer):
    id = "house"; label = "House load"

    def _sensor_id(self) -> str:
        # Versuche mehrere gängige Keys
        for k in ("house_load", "house_consumption", "home_consumption"):
            sid = _map(k)
            if sid:
                return sid
        # Kein Sensor konfiguriert -> Hauslast wird implizit in read_surplus_kw abgedeckt
        return ""

    def compute_desire(self, ctx: Ctx | None = None) -> Desire:
        sid = self._sensor_id()
        if not sid:
            # Keine explizite Hauslast-Anforderung – Surplus-Logik deckt das ab
            return Desire(wants=False, min_kw=0.0, max_kw=0.0, must_run=False, reason="no house sensor")
        raw = get_sensor_value(sid)
        need_kw = _kw(_num(raw, 0.0))
        # Hauslast ist Muss-Last (wenn Sensor vorhanden)
        return Desire(wants=True, min_kw=need_kw, max_kw=need_kw, must_run=True, reason="measured house load")

    def apply_allocation(self, ctx: Ctx, alloc_kw: float) -> None:
        # Hauslast ist nicht aktiv schaltbar; nichts zu tun.
        return
