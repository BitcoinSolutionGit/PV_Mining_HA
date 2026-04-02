# ui_pages/common.py
import os
import yaml
import dash
from dash import html, dcc

from services.utils import load_yaml

CONFIG_DIR = "/config/pv_mining_addon"
MAIN_CFG = os.path.join(CONFIG_DIR, "pv_mining_local_config.yaml")

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_CONFIG = os.path.join(ADDON_ROOT, "config.yaml")

DEFAULT_README_DE = "https://github.com/BitcoinSolutionGit/PV_Mining_HA/blob/master/Readme_DE.md"
DEFAULT_README_EN = "https://github.com/BitcoinSolutionGit/PV_Mining_HA/blob/master/Readme_EN.md"


def ui_background_color() -> str:
    """Read addon UI background from config.yaml, fall back to the dark theme base."""
    try:
        with open(ADDON_CONFIG, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        ui = ((y.get("pv_mining_addon") or {}).get("ui") or {})
        col = (ui.get("background_color") or "").strip()
        return col or "#1b2230"
    except Exception:
        return "#1b2230"


def page_wrap(children):
    col = ui_background_color()
    return html.Div(
        children,
        id="app-root",
        style={
            "--bg-color": col,
            "background": col,
            "minHeight": "100vh",
            "margin": 0,
            "padding": 0,
            "color": "#f4f7ff",
        },
    )


def number_stepper(
    input_id,
    value,
    *,
    step=1,
    min=None,
    max=None,
    width_px=140,
    persistence=None,
    persistence_type=None,
):
    if isinstance(width_px, (int, float)):
        width_num = int(width_px)
        width_value = f"{width_num if width_num >= 176 else 176}px"
    else:
        width_value = str(width_px)
    input_kwargs = {
        "id": input_id,
        "type": "text",
        "value": value,
        "step": step,
        "inputMode": "decimal",
        "className": "app-num-stepper-input",
        "style": {"width": "100%"},
    }
    if min is not None:
        input_kwargs["min"] = min
    if max is not None:
        input_kwargs["max"] = max
    if persistence is not None:
        input_kwargs["persistence"] = persistence
    if persistence_type is not None:
        input_kwargs["persistence_type"] = persistence_type

    return html.Div(
        [
            html.Button("-", type="button", className="app-num-stepper-btn minus"),
            dcc.Input(**input_kwargs),
            html.Button("+", type="button", className="app-num-stepper-btn plus"),
        ],
        className="app-num-stepper",
        style={"width": width_value},
    )


def _btn_style():
    return {
        "display": "inline-block",
        "padding": "10px 14px",
        "border": "1px solid rgba(191, 205, 229, 0.18)",
        "borderRadius": "999px",
        "textDecoration": "none",
        "fontWeight": "600",
        "background": "rgba(255, 255, 255, 0.06)",
        "color": "#c9d4e8",
        "cursor": "pointer",
        "boxShadow": "0 18px 42px rgba(5, 10, 20, 0.24)",
    }


def _chip_style():
    return {
        "textDecoration": "none",
        "padding": "8px 12px",
        "border": "1px solid rgba(191, 205, 229, 0.18)",
        "borderRadius": "999px",
        "display": "inline-block",
        "marginRight": "8px",
        "background": "rgba(255, 255, 255, 0.06)",
        "color": "#c9d4e8",
    }


def _popup_style():
    return {
        "marginTop": "8px",
        "padding": "8px 10px",
        "border": "1px solid rgba(191, 205, 229, 0.18)",
        "borderRadius": "14px",
        "background": "rgba(12, 18, 30, 0.98)",
        "display": "inline-block",
        "boxShadow": "0 18px 42px rgba(5, 10, 20, 0.24)",
    }


def _container_style():
    return {
        "textAlign": "center",
        "marginTop": "28px",
        "opacity": "0.98",
        "display": "flex",
        "gap": "12px",
        "justifyContent": "center",
        "alignItems": "center",
        "flexWrap": "wrap",
    }


def _readme_urls():
    cfg = load_yaml(MAIN_CFG, {}) or {}
    docs = cfg.get("docs", {}) if isinstance(cfg, dict) else {}
    de = (docs.get("readme_de_url") or os.getenv("README_URL_DE") or DEFAULT_README_DE).strip()
    en = (docs.get("readme_en_url") or os.getenv("README_URL_EN") or DEFAULT_README_EN).strip()
    return de, en


def footer_license():
    license_href = dash.get_relative_path("/license")
    de_url, en_url = _readme_urls()

    license_btn = html.A(
        "License",
        href=license_href,
        target="_blank",
        rel="noopener noreferrer",
        style=_btn_style(),
    )

    readme_btn = html.Details(
        [
            html.Summary("Readme", style={**_btn_style(), "listStyle": "none"}),
            html.Div(
                [
                    html.A("DE", href=de_url, target="_blank", rel="noopener noreferrer", style=_chip_style()),
                    html.A("EN", href=en_url, target="_blank", rel="noopener noreferrer", style=_chip_style()),
                ],
                className="footer-popup",
                style=_popup_style(),
            ),
        ],
        style={"display": "inline-block"},
    )

    return html.Div([license_btn, readme_btn], className="footer-license", style=_container_style())
