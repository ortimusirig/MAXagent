"""Top-level layout: header + a three-workspace shell (Command Center / Ask MAX / Work Strategy
Studio) per 50 - UI and Experience.

- Command Center: queue-first triage. Filters live IN the table (per-column) + the Review Priorities
  tiles; no global scope bar. (see ui/command_center.py)
- Ask MAX: pure chat + artifact tabs. No visible scope bar - the asset/time/review scope is a hidden
  carrier set by a Command Center drill-in or resolved from the question (entity extraction).
- Work Strategy Studio: the governed review screen (owns the visible context bar); wired next slice.

All three workspaces stay mounted; a callback toggles visibility so the chat/artifact callbacks keep
firing regardless of which workspace is on screen.
"""

from __future__ import annotations

from dash import dcc, html

from ..orchestrator import MaxAgent
from .command_center import render_command_center
from .theme import COLORS, FONT, MUTED

_TIME_WINDOWS = ["LAST_12_MONTHS", "LAST_24_MONTHS", "LAST_36_MONTHS"]
_REVIEW_TYPES = [
    "PM effectiveness and strategy review",
    "Frequency change review",
    "CBM conversion review",
    "Task list cleanup review",
    "Retire / run-to-failure review",
]
_WORKSPACES = [("command", "Command Center"), ("ask", "Ask MAX"), ("studio", "Work Strategy Studio")]


def nav_button_style(active: bool) -> dict:
    return {
        "border": "none", "borderBottom": f"3px solid {COLORS['oxy'] if active else 'transparent'}",
        "background": "transparent", "cursor": "pointer", "padding": "12px 20px",
        "fontSize": "14px", "fontWeight": 700 if active else 600,
        "color": COLORS["oxy"] if active else COLORS["muted"],
    }


def build_layout(agent: MaxAgent, portfolio_health: dict) -> html.Div:
    fleet = agent._fleet_index
    asset_options = [{"label": eq, "value": eq} for eq in fleet]
    first = next(iter(fleet))
    mode = agent.client.mode()

    header = html.Div([
        html.Div([
            html.Div("MAX Agent", style={"fontSize": "20px", "fontWeight": 800, "color": "white"}),
            html.Div("Governed preventive-maintenance strategy copilot for Oxy - draft-only, human-approved",
                     style={"fontSize": "12px", "color": "#cfe0f3"}),
        ]),
        html.Div(f"{mode}  |  default_oxy", style={"fontSize": "12px", "color": "#9fc0e6"}),
    ], style={"background": COLORS["oxy"], "padding": "14px 22px", "display": "flex",
              "justifyContent": "space-between", "alignItems": "center"})

    nav = html.Div([
        html.Button(label, id=f"nav-{key}", n_clicks=0, style=nav_button_style(key == "command"))
        for key, label in _WORKSPACES
    ], style={"display": "flex", "gap": "4px", "padding": "0 18px", "background": "white",
              "borderBottom": f"1px solid {COLORS['line']}"})

    # --- Command Center workspace (queue-first landing; filters live in the table) ---
    ws_command = html.Div(render_command_center(portfolio_health), id="ws-command", style={"display": "block"})

    # --- Ask MAX workspace: pure chat + artifact tabs; scope is a hidden carrier ---
    hidden_scope = html.Div([
        dcc.Dropdown(id="asset-dropdown", options=asset_options, value=first, clearable=False),
        dcc.Dropdown(id="time-window", options=[{"label": t, "value": t} for t in _TIME_WINDOWS],
                     value="LAST_24_MONTHS", clearable=False),
        dcc.Dropdown(id="review-type", options=[{"label": t, "value": t} for t in _REVIEW_TYPES],
                     value=_REVIEW_TYPES[0], clearable=False),
        html.Div(id="context-bar"),
    ], style={"display": "none"})

    left = html.Div([
        html.Div("Ask MAX", style={"fontWeight": 700, "color": COLORS["ink"], "marginBottom": "8px"}),
        html.Div([
            html.Div(id="chat-echo"),
            html.Div(id="chat-output"),
            html.Div(id="chat-status"),
        ], id="chat-scroll", style={
            "flex": "1", "overflowY": "auto", "display": "flex", "flexDirection": "column",
            "gap": "10px", "padding": "4px 2px 10px 2px",
        }),
        html.Div([
            dcc.Input(id="chat-input", type="text", debounce=False,
                      placeholder="Ask MAX about a PM or the fleet...",
                      style={"flex": "1", "padding": "10px", "fontSize": "13px", "boxSizing": "border-box",
                             "border": f"1px solid {COLORS['line']}", "borderRadius": "10px"}),
            html.Button("Ask", id="chat-send", n_clicks=0,
                        style={"border": "none", "borderRadius": "10px", "padding": "10px 18px",
                               "background": COLORS["oxy"], "color": "white", "fontWeight": 700, "cursor": "pointer"}),
        ], style={"display": "flex", "gap": "8px", "alignItems": "center",
                  "borderTop": f"1px solid {COLORS['line']}", "paddingTop": "10px"}),
        html.Div("Straw man: every value is synthetic or PROPOSED; MAX does not decide Oxy policy.",
                 style={**MUTED, "marginTop": "6px", "fontSize": "11px"}),
    ], style={"width": "34%", "minWidth": "320px", "padding": "18px", "borderRight": f"1px solid {COLORS['line']}",
              "boxSizing": "border-box", "display": "flex", "flexDirection": "column", "height": "100%"})

    tabs = dcc.Tabs(id="artifact-tabs", value="decision", children=[
        dcc.Tab(label="Decision", value="decision", children=html.Div(id="tab-decision", style={"padding": "12px"})),
        dcc.Tab(label="Evidence", value="evidence", children=html.Div(id="tab-evidence", style={"padding": "12px"})),
        dcc.Tab(label="Comparison", value="comparison", children=html.Div(id="tab-comparison", style={"padding": "12px"})),
        dcc.Tab(label="SAP Package", value="sap", children=html.Div(id="tab-sap", style={"padding": "12px"})),
        dcc.Tab(label="Tool Trace", value="trace", children=html.Div(id="tab-trace", style={"padding": "12px"})),
    ])
    right = html.Div([tabs], style={"flex": "1", "padding": "12px", "boxSizing": "border-box", "overflowY": "auto", "background": COLORS["bg"]})
    ws_ask = html.Div([
        hidden_scope,
        html.Div([left, right], style={"display": "flex", "height": "calc(100vh - 190px)"}),
    ], id="ws-ask", style={"display": "none"})

    # --- Work Strategy Studio workspace (governed approval lands next slice) ---
    ws_studio = html.Div([
        html.Div("Work Strategy Studio", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"]}),
        html.Div("The selected asset's context bar, recommendation, drafted SAP change package, and the "
                 "governed approve / request-changes / reject workflow (routed through the deterministic "
                 "approval tool - a click is not authorization) land here in the next slice.",
                 style={**MUTED, "marginTop": "8px", "maxWidth": "70ch"}),
    ], id="ws-studio", style={"display": "none", "padding": "18px 22px"})

    return html.Div([
        header, nav, ws_command, ws_ask, ws_studio,
        dcc.Store(id="workspace", data="command"),
        dcc.Store(id="cc-active-priority"),
        dcc.Store(id="approval-audit", data=[]),
        dcc.Store(id="chat-question"),
        dcc.Store(id="session-id"),
        dcc.Interval(id="thinking-interval", interval=600, n_intervals=0),
    ], style={"fontFamily": FONT, "background": COLORS["bg"], "color": COLORS["ink"], "minHeight": "100vh"})
