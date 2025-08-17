from typing import Optional
from .base import Consumer
from .cooling import CoolingConsumer
from .house import HouseLoadConsumer
from .battery import BatteryConsumer
from .miner import MinerConsumer

def get_consumer_for_id(consumer_id: str) -> Optional[Consumer]:
    if consumer_id == "house":
        return HouseLoadConsumer()
    if consumer_id == "battery":
        return BatteryConsumer()
    if consumer_id == "cooling":
        return CoolingConsumer()
    if consumer_id.startswith("miner:"):
        mid = consumer_id.split(":", 1)[1]
        return MinerConsumer(miner_id=mid)
    return None