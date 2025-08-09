import os
import requests # bleibt für später; aktuell nicht genutzt
from .utils import load_state, save_state, iso_now

# 3) Kleiner Hinweis für später (wenn GitHub freigibt)
#
#     In deiner GitHub App die Callback URL hinterlegen (Ingress beachten!):
#     https://<dein-ha-host>/api/hassio_ingress/<dein-addon-ingress-id>/oauth/callback
#     → Wir können das exakt ableiten, sobald dein Ingress-Pfad fix ist (du loggst ihn ja bereits).
#
#     Dann:
#
#         Kommentare in githubauth.py entfernen,
#
#         im Button statt Simulation auf /oauth/start verlinken,
#
#         im Callback complete_github_oauth(...) aufrufen,
#
#         optional danach verify_license() + start_heartbeat_loop() triggern.


# Konfiguration aus Umgebungsvariablen (für später)
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN     = "https://github.com/login/oauth/access_token"
GITHUB_GRAPHQL_API     = "https://api.github.com/graphql"
GITHUB_SPONSOR_ACCOUNT = os.getenv("GITHUB_SPONSOR_ACCOUNT", "DEIN_ACCOUNT_ODER_ORG")

def _set_premium_enabled(val: bool, payload: dict = None):
    st = load_state()
    st["premium_enabled"] = bool(val)
    if payload is not None:
        st["license_payload"] = payload
    save_state(st)

# --- Simulation ---
def simulate_sponsor_activation() -> bool:
    """Simulation: so tun, als ob GitHub Sponsorship aktiv ist."""
    payload = {
        "issuer": "github",
        "plan": "monthly",
        "sponsor": "demo_user",
        "product": "ha-pv-mining",
        "issued_at": iso_now(),
        "expires_at": None,
    }
    _set_premium_enabled(True, payload)
    st = load_state()
    st["last_verify_at"] = iso_now()
    save_state(st)
    return True

# --- Echter Flow (auskommentiert) ---
# def build_github_oauth_url(redirect_uri: str, state: str) -> str:
#     import urllib.parse
#     return (
#         f"{GITHUB_OAUTH_AUTHORIZE}"
#         f"?client_id={GITHUB_CLIENT_ID}"
#         f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
#         f"&scope=read:user%20user:email%20read:org"
#         f"&state={state}"
#     )

# def exchange_code_for_token(code: str, redirect_uri: str) -> str:
#     headers = {"Accept": "application/json"}
#     data = {
#         "client_id": GITHUB_CLIENT_ID,
#         "client_secret": GITHUB_CLIENT_SECRET,
#         "code": code,
#         "redirect_uri": redirect_uri,
#     }
#     r = requests.post(GITHUB_OAUTH_TOKEN, data=data, headers=headers, timeout=10)
#     r.raise_for_status()
#     return r.json().get("access_token", "")

# def fetch_github_sponsorship(user_token: str) -> dict:
#     q = """
#     query {
#       viewer {
#         login
#         sponsorshipsAsSponsor(first: 10, activeOnly: true) {
#           nodes { sponsorable { login } tier { monthlyPriceInDollars name } }
#         }
#       }
#     }"""
#     headers = {"Authorization": f"Bearer {user_token}"}
#     r = requests.post(GITHUB_GRAPHQL_API, json={"query": q}, headers=headers, timeout=10)
#     r.raise_for_status()
#     return r.json()

# def complete_github_oauth(code: str, redirect_uri: str) -> bool:
#     token = exchange_code_for_token(code, redirect_uri)
#     data = fetch_github_sponsorship(token)
#     # TODO: prüfen, ob sponsorable.login == "DEIN_ACCOUNT"
#     return True
