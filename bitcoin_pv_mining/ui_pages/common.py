# ui_pages/common.py
import os
import dash
from dash import html
from services.utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
MAIN_CFG   = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

# Default auf GitHub-README
DEFAULT_README_DE = "https://github.com/BitcoinSolutionGit/PV_Mining_HA/blob/master/Readme_DE.md"
DEFAULT_README_EN = "https://github.com/BitcoinSolutionGit/PV_Mining_HA/blob/master/Readme_EN.md"

def ui_background_color() -> str:
    cfg = load_yaml(MAIN_CFG, {}) or {}
    col = (cfg.get("ui", {}).get("background_color") or "#F3F5F7").strip()
    return col

def page_wrap(children):
    col = ui_background_color()
    return html.Div(
        children,
        id="app-root",
        style={
            "--bg-color": col,                 # CSS-Variable (falls du sie später brauchst)
            "background": col,                 # tatsächlicher Hintergrund hier
            "minHeight": "100vh",
            "margin": 0,
            "padding": 0,
        },
    )

def _btn_style():
    return {
        "display": "inline-block",
        "padding": "6px 12px",
        "border": "1px solid #ccc",
        "borderRadius": "8px",
        "textDecoration": "none",
        "fontWeight": "600",
        "background": "white",         # neutraler als grau
        "color": "#1a73e8",            # klassisches Link-Blau
        "cursor": "pointer",
    }

def _chip_style():
    return {
        "textDecoration":"none",
        "padding":"6px 10px",
        "border":"1px solid #ccc",
        "borderRadius":"999px",
        "display":"inline-block",
        "marginRight":"8px",
        "background":"white",
        "color": "#1a73e8",            # auch die Chips in Link-Blau
    }

def _popup_style():
    return {
        "marginTop":"8px",
        "padding":"6px 8px",
        "border":"1px solid #ddd",
        "borderRadius":"10px",
        "background":"#fff",
        "display":"inline-block",
        "boxShadow":"0 4px 14px rgba(0,0,0,0.12)"
    }

def _container_style():
    return {
        "textAlign": "center",
        "marginTop": "24px",
        "opacity": "0.95",
        "display":"flex",
        "gap":"12px",
        "justifyContent":"center",
        "alignItems":"center",
        "flexWrap":"wrap",
    }

def _readme_urls():
    """Externe Links priorisieren; falls nicht konfiguriert → GitHub-Defaults."""
    cfg  = load_yaml(MAIN_CFG, {}) or {}
    docs = cfg.get("docs", {}) if isinstance(cfg, dict) else {}
    de = (docs.get("readme_de_url") or os.getenv("README_URL_DE") or DEFAULT_README_DE).strip()
    en = (docs.get("readme_en_url") or os.getenv("README_URL_EN") or DEFAULT_README_EN).strip()
    return de, en


def footer_license():
    license_href = dash.get_relative_path("/license")
    de_url, en_url = _readme_urls()

    license_btn = html.A("© License", href=license_href, target="_blank",
                         rel="noopener noreferrer", style=_btn_style())

    readme_btn = html.Details([
        # „Readme“ statt „README“ + Pfeil ausblenden
        html.Summary("Readme", style={**_btn_style(), "listStyle": "none"}),
        html.Div([
            html.A("DE", href=de_url, target="_blank", rel="noopener noreferrer", style=_chip_style()),
            html.A("EN", href=en_url, target="_blank", rel="noopener noreferrer", style=_chip_style()),
        ], style=_popup_style())
    ], style={"display":"inline-block"})

    return html.Div([license_btn, readme_btn], style=_container_style())
