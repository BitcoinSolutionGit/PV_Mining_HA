from __future__ import annotations

from services.consumers.base import BaseConsumer, Desire, Ctx

class WallboxConsumer(BaseConsumer):
    id = "wallbox"; label = "Wallbox"
    def compute_desire(self, ctx: Ctx) -> Desire:
        return Desire(False, 0.0, 0.0, reason="not configured")