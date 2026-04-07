import os
import re
import yaml

from services.utils import get_addon_version, load_state, save_state, iso_now


ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DISCLAIMER_DE_CANDIDATES = [
    "/config/pv_mining_addon/Disclaimer_DE.md",
    os.path.join(ADDON_ROOT, "Disclaimer_DE.md"),
]

DISCLAIMER_EN_CANDIDATES = [
    "/config/pv_mining_addon/Disclaimer_EN.md",
    os.path.join(ADDON_ROOT, "Disclaimer_EN.md"),
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


def _addon_scope(version: str) -> str:
    raw = str(version or "").strip()
    match = re.match(r"^\s*(\d+)\.(\d+)", raw)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    nums = re.findall(r"\d+", raw)
    if len(nums) >= 2:
        return f"{nums[0]}.{nums[1]}"
    if len(nums) == 1:
        return f"{nums[0]}.0"
    return "0.0"


def get_current_consent_scope() -> str:
    return _addon_scope(get_addon_version())


def get_stored_consent() -> dict:
    st = load_state() or {}
    raw = st.get("user_consent", {})
    consent = raw if isinstance(raw, dict) else {}
    language = str(consent.get("language", "") or "de").lower()
    if language not in ("de", "en"):
        language = "de"
    return {
        "accepted": bool(consent.get("accepted")),
        "disclaimer_version": str(
            consent.get("disclaimer_version", consent.get("version", "")) or ""
        ),
        "addon_scope": str(consent.get("addon_scope", "") or ""),
        "language": language,
        "timestamp": str(consent.get("timestamp", "") or ""),
    }


def get_required_reason() -> str:
    current = get_current_disclaimer_info()
    current_disclaimer_version = str(current.get("version", "unknown") or "unknown")
    current_scope = get_current_consent_scope()
    stored = get_stored_consent()

    if not bool(stored.get("accepted")):
        return "missing_acceptance"
    if str(stored.get("disclaimer_version", "")) != current_disclaimer_version:
        return "disclaimer_changed"
    if str(stored.get("addon_scope", "")) != current_scope:
        return "addon_scope_changed"
    return ""


def needs_consent() -> bool:
    return bool(get_required_reason())


def get_consent_status() -> dict:
    current = get_current_disclaimer_info()
    stored = get_stored_consent()
    current_disclaimer_version = str(current.get("version", "unknown") or "unknown")
    current_addon_scope = get_current_consent_scope()
    required_reason = get_required_reason()
    return {
        "required": bool(required_reason),
        "required_reason": required_reason,
        "current_version": current_disclaimer_version,
        "current_date": current.get("date", ""),
        "stored_version": str(stored.get("disclaimer_version", "") or ""),
        "current_disclaimer_version": current_disclaimer_version,
        "stored_disclaimer_version": str(stored.get("disclaimer_version", "") or ""),
        "current_addon_scope": current_addon_scope,
        "stored_addon_scope": str(stored.get("addon_scope", "") or ""),
        "accepted": bool(stored.get("accepted")),
        "language": str(stored.get("language", "de") or "de"),
        "timestamp": str(stored.get("timestamp", "") or ""),
    }


def save_user_consent(*, accepted: bool, language: str):
    st = load_state() or {}
    current = get_current_disclaimer_info()
    st["user_consent"] = {
        "accepted": bool(accepted),
        "disclaimer_version": current.get("version", "unknown"),
        "version": current.get("version", "unknown"),
        "addon_scope": get_current_consent_scope(),
        "timestamp": iso_now(),
        "language": "de" if str(language).lower().startswith("de") else "en",
    }
    save_state(st)
