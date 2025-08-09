# services/license.py
import os, requests, threading, time
from .utils import load_state, save_state, iso_now, get_addon_version

LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")
HEARTBEAT_SEC    = 60 * 10   # alle 10 Minuten

def get_token() -> str:
    return load_state().get("license_token", "")

def set_token(tok: str) -> None:
    st = load_state()
    st["license_token"] = tok
    save_state(st)

def is_premium_enabled() -> bool:
    return bool(load_state().get("premium_enabled", False))

def set_premium_enabled(flag: bool) -> None:
    st = load_state()
    st["premium_enabled"] = bool(flag)
    save_state(st)

def verify_license() -> bool:
    """Fragt /verify.php mit ?token=... ab und setzt premium_enabled entsprechend."""
    tok = get_token()
    if not tok:
        set_premium_enabled(False)
        return False
    try:
        url = f"{LICENSE_BASE_URL}/verify.php"
        r = requests.get(url, params={"token": tok}, timeout=8)
        ok = (r.status_code == 200 and r.headers.get("content-type","").startswith("application/json")
              and bool(r.json().get("ok")))
        set_premium_enabled(ok)
        st = load_state()
        st["last_verify_at"] = iso_now()
        save_state(st)
        print("[LICENSE] verify:", r.text[:200])
        return ok
    except Exception as e:
        print("[LICENSE] verify error:", e)
        return False

def heartbeat_once(addon_version: str = None) -> None:
    tok = get_token()
    if not tok:
        return
    try:
        payload = {
            "token": tok,
            "install_id": load_state().get("install_id", "unknown-install"),
            "addon_version": addon_version or get_addon_version()
        }
        r = requests.post(f"{LICENSE_BASE_URL}/heartbeat.php", json=payload, timeout=8)
        print("[LICENSE] heartbeat:", r.text[:200])
        st = load_state()
        st["last_heartbeat_at"] = iso_now()
        save_state(st)
    except Exception as e:
        print("[LICENSE] heartbeat error:", e)

def start_heartbeat_loop(addon_version: str = None):
    """Sendet Heartbeats nur, wenn premium_enabled True ist und ein Token existiert."""
    def loop():
        while True:
            if is_premium_enabled() and get_token():
                heartbeat_once(addon_version=addon_version)
            time.sleep(HEARTBEAT_SEC)
    threading.Thread(target=loop, daemon=True).start()

def issue_token_and_enable(sponsor: str = "demo_user", plan: str = "monthly") -> bool:
    """Holt Token von /issue.php und ruft anschließend verify_license()."""
    try:
        r = requests.post(f"{LICENSE_BASE_URL}/issue.php",
                          data={"sponsor": sponsor, "plan": plan}, timeout=8)
        print("[LICENSE] issue:", r.text[:200])
        js = r.json()
        if js.get("ok") and js.get("token"):
            set_token(js["token"])
            return verify_license()
        return False
    except Exception as e:
        print("[LICENSE] issue error:", e)
        return False
