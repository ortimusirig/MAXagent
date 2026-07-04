"""Top-level layout: header, top context bar (filters that drive scope), left conversation
panel (chat input + pills + answer), right artifact tabs. Queue-first: PM Health is the landing
tab (30/AppExp), and chat / row drill-through both lock the same run context."""

from __future__ import annotations

from dash import dcc, html

from ..orchestrator import MaxAgent
from .theme import COLORS, FONT, MUTED

_TIME_WINDOWS = ["LAST_12_MONTHS", "LAST_24_MONTHS", "LAST_36_MONTHS"]
_REVIEW_TYPES = [
    "PM effectiveness and strategy review",
    "Frequency change review",
    "CBM conversion review",
    "Task list cleanup review",
    "Retire / run-to-failure review",
]


def _dropdown(_id, options, value, width):
    return dcc.Dropdown(
        id=_id, options=[{"label": o, "value": o} for o in options], value=value,
        clearable=False, style={"width": width, "fontSize": "13px"},
    )


def build_layout(agent: MaxAgent) -> html.Div:
    fleet = agent._fleet_index
    asset_options = [
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

    # Top context/filter region: the controls drive the backend scope, not just the view.
    filters = html.Div([
        html.Div([html.Span("Asset", style={**MUTED, "marginRight": "6px"}),
                  dcc.Dropdown(id="asset-dropdown", options=asset_options, value=first, clearable=False,
                               style={"width": "320px", "fontSize": "13px"})],
                 style={"display": "flex", "alignItems": "center", "marginRight": "16px"}),
        html.Div([html.Span("Time window", style={**MUTED, "marginRight": "6px"}),
                  _dropdown("time-window", _TIME_WINDOWS, "LAST_24_MONTHS", "200px")],
                 style={"display": "flex", "alignItems": "center", "marginRight": "16px"}),
        html.Div([html.Span("Review type", style={**MUTED, "marginRight": "6px"}),
                  _dropdown("review-type", _REVIEW_TYPES, _REVIEW_TYPES[0], "320px")],
                 style={"display": "flex", "alignItems": "center"}),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px", "alignItems": "center",
              "padding": "12px 22px", "borderBottom": f"1px solid {COLORS['line']}", "background": "white"})

    context_bar = html.Div(id="context-bar")

    left = html.Div([
        html.Div("Ask MAX", style={"fontWeight": 700, "color": COLORS["ink"], "marginBottom": "6px"}),
        dcc.Input(id="chat-input", type="text", debounce=True,
                  placeholder="e.g. Is this compressor's PM effective? or type an asset id",
                  style={"width": "100%", "padding": "8px", "fontSize": "13px", "boxSizing": "border-box",
                         "border": f"1px solid {COLORS['line']}", "borderRadius": "8px"}),
        html.Button("Ask", id="chat-send", n_clicks=0,
                    style={"marginTop": "8px", "border": "none", "borderRadius": "8px", "padding": "8px 16px",
                           "background": COLORS["oxy"], "color": "white", "fontWeight": 700, "cursor": "pointer"}),
        html.Div(id="chat-echo", style={"marginTop": "10px"}),
        html.Div(id="tool-pills", style={"marginTop": "10px"}),
        html.Div(id="user-question", style={**MUTED, "fontStyle": "italic", "margin": "8px 0"}),
        html.Div(id="chat-output"),
        html.Div("The demo is a straw man. Every value is synthetic or PROPOSED; MAX does not decide Oxy policy.",
                 style={**MUTED, "marginTop": "12px", "fontSize": "11px"}),
    ], style={"width": "34%", "minWidth": "320px", "padding": "18px", "borderRight": f"1px solid {COLORS['line']}", "boxSizing": "border-box", "overflowY": "auto"})

    tabs = dcc.Tabs(id="artifact-tabs", value="pmhealth", children=[
        dcc.Tab(label="PM Health", value="pmhealth", children=html.Div(id="tab-pmhealth", style={"padding": "12px"})),
        dcc.Tab(label="Decision", value="decision", children=html.Div(id="tab-decision", style={"padding": "12px"})),
        dcc.Tab(label="Evidence", value="evidence", children=html.Div(id="tab-evidence", style={"padding": "12px"})),
        dcc.Tab(label="Comparison", value="comparison", children=html.Div(id="tab-comparison", style={"padding": "12px"})),
        dcc.Tab(label="SAP Package", value="sap", children=html.Div(id="tab-sap", style={"padding": "12px"})),
        dcc.Tab(label="Tool Trace", value="trace", children=html.Div(id="tab-trace", style={"padding": "12px"})),
    ])

    right = html.Div([tabs], style={"flex": "1", "padding": "12px", "boxSizing": "border-box", "overflowY": "auto", "background": COLORS["bg"]})

    body = html.Div([left, right], style={"display": "flex", "height": "calc(100vh - 150px)"})

    return html.Div([
        header, filters, context_bar, body,
        dcc.Store(id="approval-audit", data=[]),
    ], style={"fontFamily": FONT, "background": COLORS["bg"], "color": COLORS["ink"], "minHeight": "100vh"})
