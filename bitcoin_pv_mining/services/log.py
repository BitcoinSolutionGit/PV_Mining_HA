# services/log.py
import logging, os

# Zielordner (im Add-on) oder Fallback lokal beim Dev-Run
LOG_DIR = os.getenv("CONFIG_DIR", "/config/pv_mining_addon")
if not os.path.isdir(LOG_DIR):
    LOG_DIR = "."

LOG_PATH = os.path.join(LOG_DIR, "orchestrator.log")

_logger = logging.getLogger("pv-orchestrator")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt); _logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt); _logger.addHandler(ch)

def dry(msg, **kv):
    if kv:
        msg = msg + " " + " ".join(f"{k}={v}" for k, v in kv.items())
    _logger.info("[dry] " + msg)
