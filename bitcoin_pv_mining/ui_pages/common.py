# ui_pages/common.py
import os
import dash
from dash import html
from services.utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
MAIN_CFG   = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

def _readme_urls():
    cfg = load_yaml(MAIN_CFG, {}) or {}
    docs = cfg.get("docs", {}) if isinstance(cfg, dict) else {}

    de = (docs.get("readme_de_url") or os.getenv("README_URL_DE") or "").strip()
    en = (docs.get("readme_en_url") or os.getenv("README_URL_EN") or "").strip()

    # Immer klickbare Fallbacks auf interne Seiten
    base = dash.get_relative_path("/readme")
    if not de:
        de = f"{base}?lang=de"
    if not en:
        en = f"{base}?lang=en"
    return de, en

def _btn_style():
    return {
        "display": "inline-block",
        "padding": "6px 12px",
        "border": "1px solid #ccc",
        "borderRadius": "8px",
        "textDecoration": "none",
        "fontWeight": "600",
        "background": "#f5f5f5",
        "cursor": "pointer",
    }

def footer_license():
    license_href = dash.get_relative_path("/license")
    de_url, en_url = _readme_urls()

    license_btn = html.A("© License", href=license_href, target="_blank",
                         rel="noopener noreferrer", style=_btn_style())

    readme_btn = html.Details([
        html.Summary("README", style=_btn_style()),
        html.Div([
            html.A("DE", href=de_url, target="_blank", rel="noopener noreferrer",
                   style={"textDecoration":"none","padding":"6px 10px","border":"1px solid #ccc",
                          "borderRadius":"999px","display":"inline-block","marginRight":"8px",
                          "background":"white"}),

            html.A("EN", href=en_url, target="_blank", rel="noopener noreferrer",
                   style={"textDecoration":"none","padding":"6px 10px","border":"1px solid #ccc",
                          "borderRadius":"999px","display":"inline-block","background":"white"}),
        ], style={"marginTop":"8px","padding":"6px 8px","border":"1px solid #ddd",
                  "borderRadius":"10px","background":"#fff","display":"inline-block",
                  "boxShadow":"0 4px 14px rgba(0,0,0,0.12)"})
    ], style={"display":"inline-block"})

    return html.Div([license_btn, readme_btn],
                    style={"textAlign": "center", "marginTop": "24px", "opacity": "0.95",
                           "display":"flex","gap":"12px","justifyContent":"center",
                           "alignItems":"center","flexWrap":"wrap"})
