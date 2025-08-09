# services/license.py
import os
import time
import datetime as dt
import threading
import requests

from .utils import load_state, save_state, iso_now, get_addon_version

# Basis-URL deines Lizenzservers (env überschreibbar)
LICENSE_BASE_URL = os.getenv("LICENSE_BASE_URL", "https://license.bitcoinsolution.at")

# Heartbeat-Intervall (Sekunden)
HEARTBEAT_SEC = 60 * 10  # alle 10 Minuten


# -----------------------------
# State-Helpers (Token/Flags)
# -----------------------------
def get_token() -> str:
    """Liest den aktuell gespeicherten Lizenz-Token aus state.json."""
    return load_state().get("license_token", "")


def set_token(tok: str) -> None:
    """Speichert den Lizenz-Token in state.json."""
    st = load_state()
    st["license_token"] = tok
    save_state(st)


def is_premium_enabled() -> bool:
    """Gibt True zurück, wenn Premium aktiv ist (laut letztem Verify-Ergebnis)."""
    return bool(load_state().get("premium_enabled", False))


def require_premium() -> None:
    if not is_premium_enabled():
        raise RuntimeError("premium_required")


def set_premium_enabled(flag: bool) -> None:
    """Setzt das Premium-Flag in state.json."""
    st = load_state()
    st["premium_enabled"] = bool(flag)
    save_state(st)


def _cache_token_exp(expires_at_iso: str | None) -> None:
    """Schreibt expires_at (ISO) in state.json, wenn vorhanden."""
    if not expires_at_iso:
        return
    st = load_state()
    st["token_expires_at"] = expires_at_iso
    save_state(st)


def has_valid_token_cached() -> bool:
    """
    True, wenn:
      - ein Token lokal vorhanden ist
      - und ein expires_at bekannt ist
      - und jetzt < expires_at
    """
    st = load_state()
    tok = st.get("license_token", "")
    exp = st.get("token_expires_at")
    if not tok or not exp:
        return False
    try:
        exp_dt = dt.datetime.fromisoformat(exp.replace("Z", "")).replace(tzinfo=dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc) < exp_dt
    except Exception:
        return False


# -----------------------------
# Server-Calls
# -----------------------------
def verify_license() -> bool:
    """
    Fragt /verify.php?token=... beim Lizenzserver ab.
    Schreibt premium_enabled, token_expires_at und last_verify_at in state.json.
    """
    tok = get_token()
    st = load_state()
    if not tok:
        st["premium_enabled"] = False
        save_state(st)
        print("[LICENSE] verify skipped: no token", flush=True)
        return False

    try:
        url = f"{LICENSE_BASE_URL}/verify.php"
        r = requests.get(url, params={"token": tok}, timeout=8)
        ok_json = (r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"))
        js = r.json() if ok_json else {}

        valid = bool(js.get("ok"))
        st["premium_enabled"] = valid
        if isinstance(js.get("payload"), dict):
            _cache_token_exp(js["payload"].get("expires_at"))

        st["last_verify_at"] = iso_now()
        save_state(st)
        print("[LICENSE] verify:", r.text[:300], flush=True)
        return valid
    except Exception as e:
        print("[LICENSE] verify error:", e, flush=True)
        return False


def issue_token_and_enable(sponsor: str = "demo_user", plan: str = "monthly", force: bool = False) -> bool:
    """
    Holt einen Token von /issue.php und führt direkt verify() aus.
    Issue wird **nur** ausgeführt, wenn kein gültiger Token vorhanden ist – außer force=True.
    """
    if not force and has_valid_token_cached():
        print("[LICENSE] issue skipped: valid token cached", flush=True)
        return verify_license()

    try:
        r = requests.post(f"{LICENSE_BASE_URL}/issue.php",
                          data={"sponsor": sponsor, "plan": plan},
                          timeout=8)
        print("[LICENSE] issue:", r.text[:300], flush=True)
        js = r.json()
        if js.get("ok") and js.get("token"):
            set_token(js["token"])
            # expires_at (falls vom Server im payload) direkt cachen
            if isinstance(js.get("payload"), dict):
                _cache_token_exp(js["payload"].get("expires_at"))
            return verify_license()
        print("[LICENSE] issue failed", flush=True)
        return False
    except Exception as e:
        print("[LICENSE] issue error:", e, flush=True)
        return False


def heartbeat_once(addon_version: str | None = None) -> None:
    """
    Sendet einen Heartbeat an /heartbeat.php, wenn ein Token vorhanden ist.
    """
    tok = get_token()
    if not tok:
        print("[LICENSE] heartbeat skipped: no token", flush=True)
        return

    try:
        payload = {
            "token": tok,
            "install_id": load_state().get("install_id", "unknown-install"),
            "addon_version": addon_version or get_addon_version(),
        }
        r = requests.post(f"{LICENSE_BASE_URL}/heartbeat.php", json=payload, timeout=8)
        print("[LICENSE] heartbeat payload:", payload, flush=True)
        print("[LICENSE] heartbeat resp:", r.text[:300], flush=True)

        st = load_state()
        st["last_heartbeat_at"] = iso_now()
        save_state(st)
    except Exception as e:
        print("[LICENSE] heartbeat error:", e, flush=True)


def start_heartbeat_loop(addon_version: str | None = None) -> None:
    """
    Startet einen Thread, der in Intervallen Heartbeats sendet,
    aber nur wenn premium_enabled True ist und ein Token existiert.
    """
    def loop():
        while True:
            if is_premium_enabled() and get_token():
                heartbeat_once(addon_version=addon_version)
            time.sleep(HEARTBEAT_SEC)

    threading.Thread(target=loop, daemon=True).start()
