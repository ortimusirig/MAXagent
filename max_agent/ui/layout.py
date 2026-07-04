"""Top-level two-panel layout: left chat, right artifact tabs."""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from ..orchestrator import MaxAgent
from .theme import COLORS, FONT, MUTED


def build_layout(agent: MaxAgent) -> html.Div:
    fleet = agent._fleet_index
    options = [
        {"label": f"{eq}  ({a['asset_class']}, crit {a['master_data']['criticality']['code']})", "value": eq}
        for eq, a in fleet.items()
    ]
    first = next(iter(fleet))
    mode = agent.client.mode()

    header = html.Div([
        html.Div("MAX Agent", style={"fontSize": "20px", "fontWeight": 800, "color": "white"}),
        html.Div("Governed preventive-maintenance strategy copilot for Oxy - draft-only, human-approved",
                 style={"fontSize": "12px", "color": "#cfe0f3"}),
        html.Div(f"data mode: {mode}  |  Wave 1 - synthetic-first, no direct SAP write-back",
                 style={"fontSize": "11px", "color": "#9fc0e6", "marginTop": "2px"}),
    ], style={"background": COLORS["oxy"], "padding": "14px 22px"})

    left = html.Div([
        html.Div("Ask MAX about an asset", style={"fontWeight": 700, "color": COLORS["ink"], "marginBottom": "6px"}),
        dcc.Dropdown(id="asset-dropdown", options=options, value=first, clearable=False,
                     style={"marginBottom": "10px"}),
        html.Div(id="user-question", style={**MUTED, "fontStyle": "italic", "marginBottom": "10px"}),
        html.Div(id="chat-output"),
        html.Div("The demo is a straw man. Every value is synthetic or PROPOSED; MAX does not decide Oxy policy.",
                 style={**MUTED, "marginTop": "12px", "fontSize": "11px"}),
    ], style={"width": "34%", "minWidth": "320px", "padding": "18px", "borderRight": f"1px solid {COLORS['line']}", "boxSizing": "border-box", "overflowY": "auto"})

    tabs = dcc.Tabs(id="artifact-tabs", value="decision", children=[
        dcc.Tab(label="Decision", value="decision", children=html.Div(id="tab-decision", style={"padding": "12px"})),
        dcc.Tab(label="Evidence", value="evidence", children=html.Div(id="tab-evidence", style={"padding": "12px"})),
        dcc.Tab(label="PM Health", value="pmhealth", children=html.Div(id="tab-pmhealth", style={"padding": "12px"})),
        dcc.Tab(label="Comparison", value="comparison", children=html.Div(id="tab-comparison", style={"padding": "12px"})),
        dcc.Tab(label="SAP Package", value="sap", children=html.Div(id="tab-sap", style={"padding": "12px"})),
        dcc.Tab(label="Tool Trace", value="trace", children=html.Div(id="tab-trace", style={"padding": "12px"})),
    ])

    right = html.Div([tabs], style={"flex": "1", "padding": "12px", "boxSizing": "border-box", "overflowY": "auto", "background": COLORS["bg"]})

    body = html.Div([left, right], style={"display": "flex", "height": "calc(100vh - 74px)"})

    return html.Div([header, body], style={"fontFamily": FONT, "background": COLORS["bg"], "color": COLORS["ink"], "height": "100vh"})
