# services/license.py
import os, requests, threading, time, uuid
from .utils import load_state, save_state, iso_now

# === Konfiguration ===
LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")
# WICHTIG: Signierter Token (payload_b64url+'.'+sig_b64url), NICHT der alte "license_key"
LICENSE_TOKEN    = os.getenv("LICENSE_TOKEN", "").strip()

# Stabile Installations-ID (UUID). Beim ersten Start generieren & in state.json merken.
def _get_install_id() -> str:
    st = load_state()
    iid = st.get("install_id")
    if not iid:
        iid = f"ha-{uuid.uuid4()}"
        st["install_id"] = iid
        save_state(st)
    return iid

ADDON_VERSION    = os.getenv("ADDON_VERSION", "3.0.2")
HEARTBEAT_SEC    = 60 * 10  # alle 10 Minuten

# === Status-Helpers ===
def is_premium_enabled() -> bool:
    return bool(load_state().get("premium_enabled", False))

def _set_premium_enabled(val: bool):
    st = load_state()
    st["premium_enabled"] = bool(val)
    save_state(st)

# Optional: DEV-Schalter im UI behalten
def activate_premium_dev() -> bool:
    print("[DEBUG] Activate Premium Button gedrückt – DEV-Modus aktiv")
    _set_premium_enabled(True)
    st = load_state()
    st["last_heartbeat_at"] = iso_now()
    save_state(st)
    return True

# === ECHTER VERIFY ===
def verify_license() -> bool:
    """Ruft verify.php per GET mit ?token= auf, speichert Ergebnis im state.json"""
    if not LICENSE_TOKEN:
        print("[LICENSE] No LICENSE_TOKEN set -> free mode")
        _set_premium_enabled(False)
        return False
    try:
        r = requests.get(
            f"{LICENSE_BASE_URL}/verify.php",
            params={"token": LICENSE_TOKEN},  # requests URL-encodet automatisch
            timeout=8,
        )
        if r.status_code == 200 and r.headers.get("content-type","").startswith("application/json"):
            data = r.json()
            ok = bool(data.get("ok")) and data.get("status") == "valid"
            st = load_state()
            st["premium_enabled"] = ok
            st["last_verify_at"] = iso_now()
            # nützlich fürs UI/Debug:
            if "payload" in data:
                st["license_payload"] = data["payload"]
            save_state(st)
            print("[LICENSE] verify:", data)
            return ok
        print("[LICENSE] unexpected verify response:", r.status_code, r.text[:200])
    except Exception as e:
        print("[LICENSE] verify error:", e)
    return False

# === HEARTBEAT ===
def send_heartbeat():
    """POST zu heartbeat.php mit token + install_id + addon_version"""
    if not LICENSE_TOKEN:
        return
    try:
        body = {
            "token": LICENSE_TOKEN,
            "install_id": _get_install_id(),
            "addon_version": ADDON_VERSION,
        }
        r = requests.post(
            f"{LICENSE_BASE_URL}/heartbeat.php",
            json=body,
            timeout=6,
        )
        # 200 + JSON wird serverseitig immer geliefert (Fehler kommen als ok:false)
        data = {}
        try:
            data = r.json()
        except Exception:
            pass

        st = load_state()
        st["last_heartbeat_at"] = iso_now()
        # Optional im State merken, was der Server sagte (Lease etc.)
        if isinstance(data, dict):
            st["last_heartbeat_response"] = data
        save_state(st)
        print("[LICENSE] heartbeat:", data if data else r.text[:200])
    except Exception as e:
        print("[LICENSE] heartbeat error:", e)

def start_heartbeat_loop():
    def loop():
        while True:
            if is_premium_enabled():
                send_heartbeat()
            time.sleep(HEARTBEAT_SEC)
    threading.Thread(target=loop, daemon=True).start()
