# services/consumers/registry.py (Ausschnitt)
from services.consumers.house import HouseLoadConsumer
from services.consumers.battery import BatteryConsumer
from services.consumers.cooling import CoolingConsumer
from services.consumers.heater import HeaterConsumer
from services.consumers.wallbox import WallboxConsumer
from services.consumers.miner import MinerConsumer

def get_consumer_for_id(cid: str):
    if cid == "house":
        return HouseLoadConsumer()
    if cid == "battery":
        return BatteryConsumer()
    if cid == "cooling":
        return CoolingConsumer()
    if cid == "heater":
        return HeaterConsumer()
    if cid == "wallbox":
        return WallboxConsumer()
    if cid.startswith("miner:"):
        mid = cid.split(":", 1)[1]
        return MinerConsumer(mid)
    return None
