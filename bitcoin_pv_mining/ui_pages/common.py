# ui_pages/common.py
import dash
from dash import html

def footer_license():
    href = dash.get_relative_path("/license")  # Ingress-sicher
    return html.Div([
        html.A("© License", href=href, target="_blank",
               style={
                   "display": "inline-block",
                   "padding": "6px 12px",
                   "border": "1px solid #ccc",
                   "borderRadius": "8px",
                   "textDecoration": "none",
                   "fontWeight": "600"
               })
    ], style={"textAlign": "center", "marginTop": "24px", "opacity": "0.85"})
