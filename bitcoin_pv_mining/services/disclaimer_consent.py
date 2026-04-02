import os
import yaml

from services.utils import load_state, save_state, iso_now


ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DISCLAIMER_DE_CANDIDATES = [
    "/config/pv_mining_addon/Disclaimer_DE.md",
    os.path.join(ADDON_ROOT, "Disclaimer_DE.md"),
    os.path.join(ADDON_ROOT, "..", "Disclaimer_DE.md"),
]

DISCLAIMER_EN_CANDIDATES = [
    "/config/pv_mining_addon/Disclaimer_EN.md",
    os.path.join(ADDON_ROOT, "Disclaimer_EN.md"),
    os.path.join(ADDON_ROOT, "..", "Disclaimer_EN.md"),
]


def _first_existing(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return ""


def _parse_frontmatter(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if not text.startswith("---"):
            return {}
        end = text.find("\n---", 3)
        if end < 0:
            return {}
        block = text[3:end].strip()
        data = yaml.safe_load(block) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _lang_meta(lang: str) -> dict:
    lang_key = "de" if str(lang).lower().startswith("de") else "en"
    path = _first_existing(DISCLAIMER_DE_CANDIDATES if lang_key == "de" else DISCLAIMER_EN_CANDIDATES)
    meta = _parse_frontmatter(path)
    return {
        "lang": lang_key,
        "path": path,
        "version": str(meta.get("version", "") or "").strip(),
        "date": str(meta.get("date", "") or "").strip(),
    }


def get_current_disclaimer_info() -> dict:
    de = _lang_meta("de")
    en = _lang_meta("en")

    de_ver = de.get("version", "")
    en_ver = en.get("version", "")
    if de_ver and en_ver:
        current_version = de_ver if de_ver == en_ver else f"de:{de_ver}|en:{en_ver}"
    else:
        current_version = de_ver or en_ver or "unknown"

    return {
        "version": current_version,
        "date": de.get("date") or en.get("date") or "",
        "de": de,
        "en": en,
    }


def get_stored_consent() -> dict:
    st = load_state() or {}
    consent = st.get("user_consent", {})
    return consent if isinstance(consent, dict) else {}


def needs_consent() -> bool:
    current_version = get_current_disclaimer_info().get("version", "unknown")
    stored = get_stored_consent()
    return (not bool(stored.get("accepted"))) or (str(stored.get("version", "")) != str(current_version))


def get_consent_status() -> dict:
    current = get_current_disclaimer_info()
    stored = get_stored_consent()
    language = str(stored.get("language", "") or "de").lower()
    if language not in ("de", "en"):
        language = "de"
    return {
        "required": needs_consent(),
        "current_version": current.get("version", "unknown"),
        "current_date": current.get("date", ""),
        "stored_version": str(stored.get("version", "") or ""),
        "accepted": bool(stored.get("accepted")),
        "language": language,
        "timestamp": str(stored.get("timestamp", "") or ""),
    }


def save_user_consent(*, accepted: bool, language: str):
    st = load_state() or {}
    current = get_current_disclaimer_info()
    st["user_consent"] = {
        "accepted": bool(accepted),
        "version": current.get("version", "unknown"),
        "timestamp": iso_now(),
        "language": "de" if str(language).lower().startswith("de") else "en",
    }
    save_state(st)

