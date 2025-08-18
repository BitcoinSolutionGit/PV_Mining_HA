from __future__ import annotations

from services.consumers.base import BaseConsumer, Desire, Ctx

class HeaterConsumer(BaseConsumer):
    id = "heater"; label = "Water Heater"
    def compute_desire(self, ctx: Ctx) -> Desire:
        return Desire(False, 0.0, 0.0, reason="not configured")