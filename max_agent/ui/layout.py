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
from .artifact_catalog import preview_empty
from .command_center import render_command_center
from .dashboard_embed import render_aibi_dashboard
from .studio import render_studio
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
            html.Img(src="/assets/oxy-logo.png", alt="OXY",
                     style={"height": "32px", "width": "auto", "display": "block"}),
            html.Div([
                html.Div("MAX Agent", style={"fontSize": "20px", "fontWeight": 800, "color": COLORS["ink"]}),
                html.Div("Governed Preventive Maintenance Agent",
                         style={"fontSize": "12px", "color": COLORS["muted"]}),
            ]),
        ], style={"display": "flex", "alignItems": "center", "gap": "12px"}),
        html.Div(f"{mode}  |  default_oxy", style={"fontSize": "12px", "color": COLORS["muted"]}),
    ], style={"background": "white", "padding": "14px 22px", "display": "flex",
              "justifyContent": "space-between", "alignItems": "center",
              "borderBottom": f"1px solid {COLORS['line']}"})

    nav = html.Div([
        html.Button(label, id=f"nav-{key}", n_clicks=0, style=nav_button_style(key == "command"))
        for key, label in _WORKSPACES
    ], style={"display": "flex", "gap": "4px", "padding": "0 18px", "background": "white",
              "borderBottom": f"1px solid {COLORS['line']}"})

    # --- Command Center workspace (queue-first landing; filters live in the table) ---
    ws_command = html.Div(render_command_center(portfolio_health), id="ws-command", style={"display": "block"})

    # --- Ask MAX workspace: pure chat + artifact tabs; scope is a hidden carrier ---
    # The scope dropdowns now live (visibly) in the Studio filter bar below; Ask MAX only needs the
    # hidden context-bar output target (Ask MAX has no visible scope bar, by design).
    hidden_scope = html.Div([html.Div(id="context-bar")], style={"display": "none"})

    left = html.Div([
        html.Div("Ask MAX", style={"fontWeight": 700, "color": COLORS["ink"], "marginBottom": "8px"}),
        html.Div([
            html.Div(id="chat-history"),   # accumulated transcript (oldest -> newest), re-rendered from chat-messages
            html.Div(id="chat-status"),    # live "MAX is thinking..." indicator, sits below the newest turn
            html.Div(id="chat-scroll-anchor", style={"display": "none"}),  # auto-scroll target
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
    ], style={"width": "34%", "minWidth": "320px", "padding": "18px", "borderRight": f"1px solid {COLORS['line']}",
              "boxSizing": "border-box", "display": "flex", "flexDirection": "column", "height": "100%"})

    # Ask MAX right panel per 50-UI: Artifacts (stacked objects) / Dashboard (fleet PM Health) /
    # conditional Preview. The decision + gate are narrated in the chat; the SAP package lives in Studio.
    # Empty at start; all three build up as you chat (callbacks populate them once MAX answers).
    tabs = dcc.Tabs(id="artifact-tabs", value="artifacts", children=[
        dcc.Tab(label="Artifacts", value="artifacts", children=html.Div(id="tab-artifacts", style={"padding": "12px"})),
        dcc.Tab(label="Dashboard", value="dashboard",
                children=html.Div(render_aibi_dashboard(portfolio_health), id="tab-dashboard", style={"padding": "12px"})),
        dcc.Tab(label="Preview", value="preview",
                children=html.Div(preview_empty(), id="tab-preview", style={"padding": "12px"})),
        dcc.Tab(label="Governance Trace", value="trace", children=html.Div(id="tab-trace", style={"padding": "12px"})),
    ])
    right = html.Div([tabs], style={"flex": "1", "padding": "12px", "boxSizing": "border-box", "overflowY": "auto", "background": COLORS["bg"]})
    ws_ask = html.Div([
        hidden_scope,
        html.Div([left, right], style={"display": "flex", "height": "calc(100vh - 190px)"}),
    ], id="ws-ask", style={"display": "none"})

    # --- Work Strategy Studio workspace (governed review; owns the visible scope filter bar) ---
    # Studio is a STANDALONE workflow: its own Asset / Time window / Review type filters drive the
    # governed review directly - no chat and no Command Center drill-in required. (A Command Center
    # drill-in or a chat still set the same shared dropdowns, so continuity is preserved.) The on_studio
    # callback fills studio-body for the selected scope; render_studio() draws the empty guidance state.
    _lbl = {"fontSize": "11px", "fontWeight": 700, "color": COLORS["muted"], "textTransform": "uppercase",
            "letterSpacing": "0.05em", "marginBottom": "4px"}

    def _field(label, comp, min_width):
        return html.Div([html.Div(label, style=_lbl), comp], style={"minWidth": min_width, "flex": "1"})

    studio_filters = html.Div([
        _field("Asset", dcc.Dropdown(id="asset-dropdown", options=asset_options, value=first, clearable=False), "190px"),
        _field("Time window", dcc.Dropdown(id="time-window", options=[{"label": t, "value": t} for t in _TIME_WINDOWS],
                                           value="LAST_24_MONTHS", clearable=False), "170px"),
        _field("Review type", dcc.Dropdown(id="review-type", options=[{"label": t, "value": t} for t in _REVIEW_TYPES],
                                           value=_REVIEW_TYPES[0], clearable=False), "260px"),
    ], style={"display": "flex", "gap": "14px", "alignItems": "flex-end", "padding": "14px 22px",
              "borderBottom": f"1px solid {COLORS['line']}", "background": "#fbfdff"})

    ws_studio = html.Div([
        studio_filters,
        html.Div(render_studio(None), id="studio-body"),
    ], id="ws-studio", style={"display": "none"})

    # Full-screen busy overlay: shown while a PM summarization (AI) call is in-flight. Fixed + full
    # viewport + top z-index so it covers the tab bar and both panels and intercepts every click
    # (blocks duplicate row-clicks). Toggled via the callback `running=` arg; positioning lives in
    # max.css (.busy-overlay); only `display` flips here.
    busy_overlay = html.Div([
        html.Div(className="max-spinner"),
        html.Div("Analyzing and summarizing PM…",
                 style={"marginTop": "14px", "fontSize": "14px", "fontWeight": 600, "color": COLORS["ink"]}),
    ], id="busy-overlay", className="busy-overlay", style={"display": "none"})

    return html.Div([
        header, nav, ws_command, ws_ask, ws_studio, busy_overlay,
        dcc.Store(id="workspace", data="command"),
        dcc.Store(id="cc-last-eid"),  # last PM asked to summarize (drives Retry after an error)
        dcc.Store(id="cc-active-priority"),
        dcc.Store(id="approval-audit", data=[]),
        dcc.Store(id="chat-question"),
        dcc.Store(id="chat-artifacts"),  # model-selected artifact names for the current answer
        dcc.Store(id="chat-messages", data=[]),  # accumulated Ask MAX transcript (user + assistant turns)
        dcc.Store(id="artifacts-history", data=[]),   # accumulated artifact sets, one per answered question
        dcc.Store(id="artifacts-collapsed", data=[]), # turn numbers whose artifact history card is collapsed
        dcc.Store(id="trace-collapsed", data=[]),     # turn numbers whose governance-trace card is collapsed
        dcc.Store(id="session-id"),
        dcc.Interval(id="thinking-interval", interval=600, n_intervals=0),
    ], style={"fontFamily": FONT, "background": COLORS["bg"], "color": COLORS["ink"], "minHeight": "100vh"})
