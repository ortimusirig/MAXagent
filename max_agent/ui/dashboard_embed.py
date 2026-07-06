"""AI/BI (Databricks Lakeview) dashboard embed for the Ask MAX 'Dashboard' tab.

Primary: embed the published Databricks AI/BI dashboard (dashboards/pm_health.lvdash.json) in an
iframe when AIBI_DASHBOARD_EMBED_URL is set. On Databricks Apps in the same workspace the viewer's
SSO session carries the auth; see dashboards/DEPLOY_AIBI.md for publishing + embedding.

Fallback: until it is deployed and the URL is set, render the SAME governed fleet metrics with the
in-app Plotly charts so the tab is never empty. Both surfaces read one governed truth
(portfolio_health()), so the AI/BI dashboard can never diverge from the app's decisions.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from dash import html

from .theme import COLORS, MUTED


def aibi_embed_url() -> Optional[str]:
    return (os.environ.get("AIBI_DASHBOARD_EMBED_URL") or "").strip() or None


def aibi_link_url() -> Optional[str]:
    return (os.environ.get("AIBI_DASHBOARD_URL") or "").strip() or None


def _header() -> html.Div:
    link = aibi_link_url()
    kids = [
        html.Div("PM Health - AI/BI dashboard", style={"fontSize": "15px", "fontWeight": 800, "color": COLORS["ink"]}),
        html.Div("Governed, draft-only. Counts only - no realized-savings implied (thresholds null; value baseline-only).",
                 style={**MUTED, "fontSize": "12px"}),
    ]
    left = html.Div(kids)
    if link:
        btn = html.A("Open in Databricks", href=link, target="_blank",
                     style={"border": f"1px solid {COLORS['oxy']}", "borderRadius": "8px", "padding": "7px 14px",
                            "color": COLORS["oxy"], "fontWeight": 700, "fontSize": "12px", "textDecoration": "none",
                            "whiteSpace": "nowrap"})
        return html.Div([left, btn], style={"display": "flex", "justifyContent": "space-between",
                                             "alignItems": "center", "marginBottom": "10px"})
    return html.Div(left, style={"marginBottom": "10px"})


def render_aibi_dashboard(health: Optional[Dict[str, Any]] = None) -> html.Div:
    """The Dashboard tab body: the embedded Databricks AI/BI dashboard, or an in-app mirror as fallback."""
    embed = aibi_embed_url()
    header = _header()

    if embed:
        frame = html.Iframe(src=embed, style={"width": "100%", "height": "760px", "border": "0",
                                              "borderRadius": "10px", "background": "white"})
        return html.Div([header, frame])

    # Fallback (not embedded yet): the same governed metrics, rendered in-app.
    note = html.Div(
        "Databricks AI/BI dashboard not embedded yet - showing the same governed fleet metrics in-app. "
        "Deploy dashboards/pm_health.lvdash.json (+ pm_health_dashboard_setup.sql) and set "
        "AIBI_DASHBOARD_EMBED_URL to embed the live one. See dashboards/DEPLOY_AIBI.md.",
        style={"background": "#fff8e6", "border": "1px solid #f0d98c", "borderRadius": "8px",
               "padding": "9px 12px", "fontSize": "12px", "color": "#7a5b00", "marginBottom": "12px"},
    )
    if health is None:
        return html.Div([header, note, html.Div("No fleet data available.", style=MUTED)])
    from .artifacts import render_pm_dashboard
    return html.Div([header, note, render_pm_dashboard(health)])
