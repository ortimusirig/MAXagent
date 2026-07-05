"""Top-level layout: header + global filters + a three-workspace shell (Command Center / Ask MAX /
Work Strategy Studio) ported from the design prototype onto the governed core.

- Command Center: queue-first landing - the PM Health triage queue + gate/readiness/criticality charts,
  all computed deterministically by ``portfolio_health()``. Click a row to open the asset in Ask MAX.
- Ask MAX: the ChatGPT-style chat panel (governed, evidence-first) + the artifact tabs.
- Work Strategy Studio: recommendation + governed approval (wired in the next slice).

All three workspaces stay mounted; a callback toggles visibility, so the chat/artifact callbacks keep
firing regardless of which workspace is on screen.
"""

from __future__ import annotations

from dash import dcc, html

from ..orchestrator import MaxAgent
from .artifacts import render_pm_health
from .theme import COLORS, FONT, MUTED, STATUS_COLORS

_TIME_WINDOWS = ["LAST_12_MONTHS", "LAST_24_MONTHS", "LAST_36_MONTHS"]
_REVIEW_TYPES = [
    "PM effectiveness and strategy review",
    "Frequency change review",
    "CBM conversion review",
    "Task list cleanup review",
    "Retire / run-to-failure review",
]

_WORKSPACES = [("command", "Command Center"), ("ask", "Ask MAX"), ("studio", "Work Strategy Studio")]


def _dropdown(_id, options, value, width):
    return dcc.Dropdown(
        id=_id, options=[{"label": o, "value": o} for o in options], value=value,
        clearable=False, style={"width": width, "fontSize": "13px"},
    )


def nav_button_style(active: bool) -> dict:
    return {
        "border": "none", "borderBottom": f"3px solid {COLORS['oxy'] if active else 'transparent'}",
        "background": "transparent", "cursor": "pointer", "padding": "12px 20px",
        "fontSize": "14px", "fontWeight": 700 if active else 600,
        "color": COLORS["oxy"] if active else COLORS["muted"],
    }


def _tile(label: str, value, color: str) -> html.Div:
    return html.Div([
        html.Div(str(value), style={"fontSize": "26px", "fontWeight": 800, "color": color}),
        html.Div(label, style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "2px"}),
    ], style={"background": "white", "border": f"1px solid {COLORS['line']}", "borderRadius": "12px",
              "padding": "14px 18px", "minWidth": "130px", "flex": "1"})


def _command_center(portfolio_health: dict) -> html.Div:
    metrics = (portfolio_health or {}).get("metrics", {})
    by_gate = metrics.get("by_gate_status", {})
    rows = (portfolio_health or {}).get("rows", [])
    tiles = html.Div([
        _tile("Assets in scope", metrics.get("population_count", len(rows)), COLORS["ink"]),
        _tile("Blocked", by_gate.get("BLOCKED", 0), STATUS_COLORS.get("BLOCKED", COLORS["ink"])),
        _tile("Review required", by_gate.get("REVIEW_REQUIRED", 0), STATUS_COLORS.get("REVIEW_REQUIRED", COLORS["ink"])),
        _tile("Draft only", by_gate.get("DRAFT_ONLY", 0), STATUS_COLORS.get("DRAFT_ONLY", COLORS["ink"])),
        _tile("Pass", by_gate.get("PASS", 0), STATUS_COLORS.get("PASS", COLORS["ink"])),
        _tile("Do-not-optimize", metrics.get("do_not_optimize_count", 0), COLORS["muted"]),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "16px"})
    return html.Div([
        html.Div("Command Center", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"], "marginBottom": "2px"}),
        html.Div("Fleet PM triage - highest-attention PMs first. Click a row to open it in Ask MAX.",
                 style={**MUTED, "marginBottom": "14px"}),
        tiles,
        render_pm_health(portfolio_health),
    ], style={"padding": "18px 22px"})


def build_layout(agent: MaxAgent, portfolio_health: dict) -> html.Div:
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

    # Workspace nav (Command Center / Ask MAX / Work Strategy Studio).
    nav = html.Div([
        html.Button(label, id=f"nav-{key}", n_clicks=0, style=nav_button_style(key == "command"))
        for key, label in _WORKSPACES
    ], style={"display": "flex", "gap": "4px", "padding": "0 18px", "background": "white",
              "borderBottom": f"1px solid {COLORS['line']}"})

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

    # --- Command Center workspace (queue-first landing) ---
    ws_command = html.Div(_command_center(portfolio_health), id="ws-command", style={"display": "block"})

    # --- Ask MAX workspace (chat + artifact tabs) ---
    left = html.Div([
        html.Div("Ask MAX", style={"fontWeight": 700, "color": COLORS["ink"], "marginBottom": "8px"}),
        html.Div([
            html.Div(id="chat-echo"),      # the user's question (bubble)
            html.Div(id="chat-output"),    # MAX's answer (bubble); empty until you ask
            html.Div(id="chat-status"),    # live "MAX is thinking..." indicator
        ], id="chat-scroll", style={
            "flex": "1", "overflowY": "auto", "display": "flex", "flexDirection": "column",
            "gap": "10px", "padding": "4px 2px 10px 2px",
        }),
        html.Div([
            dcc.Input(id="chat-input", type="text", debounce=False,
                      placeholder="Ask MAX about this asset...",
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
        html.Div(id="context-bar"),
        html.Div([left, right], style={"display": "flex", "height": "calc(100vh - 210px)"}),
    ], id="ws-ask", style={"display": "none"})

    # --- Work Strategy Studio workspace (governed approval lands next slice) ---
    ws_studio = html.Div([
        html.Div("Work Strategy Studio", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"]}),
        html.Div("The selected asset's recommendation, drafted SAP change package, and the governed "
                 "approve / request-changes / reject workflow (routed through the deterministic approval "
                 "tool - a click is not authorization) land here in the next slice.",
                 style={**MUTED, "marginTop": "8px", "maxWidth": "70ch"}),
    ], id="ws-studio", style={"display": "none", "padding": "18px 22px"})

    return html.Div([
        header, nav, filters, ws_command, ws_ask, ws_studio,
        dcc.Store(id="workspace", data="command"),
        dcc.Store(id="approval-audit", data=[]),
        dcc.Store(id="chat-question"),
        dcc.Store(id="session-id"),
        dcc.Interval(id="thinking-interval", interval=600, n_intervals=0),
    ], style={"fontFamily": FONT, "background": COLORS["bg"], "color": COLORS["ink"], "minHeight": "100vh"})
