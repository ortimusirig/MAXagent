"""Interactive Dash prototype for the Ask MAX artifact-stack experience.

This is a design handoff prototype, not a production entry point.

Intent:
- Left chat panel owns interpretation: Overview, Key Insights, Recommendation and Governance.
- Right Artifacts panel owns evidence only: charts, tables, SQL/Genie preview, gate trace.
- Artifacts are vertically stacked and visible inline; no click-to-open placeholder cards.
- Preview is conditional. It appears only when the prompt resolves to a PM/equipment context.

Run locally:
    python prototypes/ask_max_artifact_stack_dash.py
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update


COLORS = {
    "bg": "#f4f6f9",
    "panel": "#ffffff",
    "ink": "#17242f",
    "muted": "#5b6b7a",
    "line": "#d9e2ef",
    "oxy": "#0b5cab",
    "active": "#0647b7",
    "green": "#15803d",
    "red": "#c1261b",
    "orange": "#f2a000",
    "orange_text": "#b46b00",
    "chip": "#eef4fb",
}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class AskState:
    workspace: str = "ask"
    panel: str = "artifacts"
    query: str = "Should we change PM strategy for PUMP-4110?"
    resolved_asset: str | None = "PUMP-4110"

    @property
    def has_preview(self) -> bool:
        return bool(self.resolved_asset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "panel": self.panel,
            "query": self.query,
            "resolved_asset": self.resolved_asset,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AskState":
        if not value:
            return cls()
        return cls(
            workspace=value.get("workspace") or "ask",
            panel=value.get("panel") or "artifacts",
            query=value.get("query") or "Should we change PM strategy for PUMP-4110?",
            resolved_asset=value.get("resolved_asset"),
        )


def resolve_asset(query: str) -> str | None:
    """Prototype-only resolver. Production should use MAX intent/context resolution."""
    text = (query or "").upper()
    match = re.search(r"\b(PUMP|VALVE|MOTOR|COMP|FAN|HX)-\d{4}\b", text)
    if match:
        return match.group(0)
    if "THIS PM" in text or "THIS ASSET" in text:
        return "PUMP-4110"
    return None


def css_text() -> str:
    return (
        """
            * { box-sizing: border-box; }
            body { margin: 0; background: #f4f6f9; }
            button { font-family: inherit; }
            .app-shell { min-height: 100vh; color: #17242f; font-family: """
        + FONT
        + """; background: #f4f6f9; }
            .topbar { height: 70px; background: #063f8f; color: white; display: flex; align-items: center; padding: 0 22px; gap: 22px; }
            .brand-mark { width: 48px; height: 48px; border-radius: 50%; background: white; color: #0647b7; display: grid; place-items: center; font-weight: 900; }
            .brand-title { font-size: 25px; line-height: 1; font-weight: 850; }
            .brand-sub { margin-top: 5px; color: #d7e7ff; font-size: 12px; }
            .top-tabs { margin-left: auto; margin-right: auto; display: flex; align-items: center; height: 100%; }
            .workspace-tab { height: 58px; min-width: 185px; padding: 0 24px; border: 1px solid rgba(255,255,255,.35); color: white; background: rgba(255,255,255,.08); font-weight: 800; cursor: pointer; }
            .workspace-tab.active { background: white; color: #063f8f; border-color: white; position: relative; }
            .workspace-tab.active::after { content: ""; position: absolute; left: 44px; right: 44px; bottom: 4px; height: 4px; background: #063f8f; }
            .right-status { display: flex; align-items: center; gap: 9px; font-size: 14px; font-weight: 800; }
            .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #39c253; }
            .avatar { width: 40px; height: 40px; border-radius: 50%; background: #f3f6fb; color: #063f8f; display: grid; place-items: center; font-weight: 850; }
            .context-row { display: flex; flex-wrap: wrap; gap: 14px; padding: 18px 24px; background: #f8fafc; border-bottom: 1px solid #d9e2ef; }
            .context-chip { height: 42px; border: 1px solid #d9e2ef; background: white; border-radius: 7px; padding: 10px 16px; display: flex; align-items: center; gap: 16px; }
            .context-chip .label { color: #5b6b7a; font-size: 14px; }
            .context-chip .value { color: #17242f; font-size: 14px; font-weight: 850; }
            .synthetic-chip { border-color: #87c99a; background: #eaf7ee; color: #15803d; font-weight: 850; }
            .main-grid { display: grid; grid-template-columns: minmax(520px, 47%) minmax(620px, 1fr); gap: 18px; padding: 18px 22px 24px; height: calc(100vh - 139px); min-height: 760px; }
            .pane { background: white; border: 1px solid #d9e2ef; border-radius: 9px; overflow: hidden; min-height: 0; }
            .pane-scroll { height: 100%; overflow-y: auto; padding: 18px; }
            .ask-row { display: flex; gap: 10px; }
            .ask-input { height: 44px; flex: 1; border: 1px solid #cbd6e4; border-radius: 7px; padding: 0 15px; font-size: 15px; color: #17242f; }
            .send-btn { width: 48px; border: 1px solid #0b5cab; background: white; color: #0b5cab; border-radius: 7px; font-size: 24px; cursor: pointer; }
            .progress { margin-top: 18px; height: 50px; border: 1px solid #d9e2ef; background: #f9fbff; border-radius: 7px; display: flex; align-items: center; gap: 26px; padding: 0 18px; }
            .max-dot { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; background: #0647b7; color: white; font-size: 12px; font-weight: 900; }
            .step-dot { width: 16px; height: 16px; border-radius: 50%; background: #15803d; display: inline-block; margin-right: 8px; vertical-align: -2px; }
            .tool-row { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin: 14px 0 6px; }
            .tool-pill { color: #15803d; border: 1px solid #87c99a; background: #eaf7ee; border-radius: 999px; padding: 7px 14px; font-size: 12px; font-weight: 800; }
            .chat-card { margin-top: 6px; margin-left: 64px; border: 1px solid #d9e2ef; border-radius: 9px; padding: 24px 24px 22px; position: relative; }
            .chat-card::before { content: "MAX"; position: absolute; left: -64px; top: 22px; width: 44px; height: 44px; border-radius: 50%; background: #0647b7; color: white; display: grid; place-items: center; font-size: 13px; font-weight: 900; }
            .section-title { color: #0647b7; font-size: 23px; font-weight: 850; margin: 0 0 14px; }
            .chat-card p { margin: 0 0 10px; line-height: 1.42; }
            .chat-card ul { margin-top: 6px; margin-bottom: 24px; padding-left: 22px; }
            .chat-card li { margin: 9px 0; line-height: 1.38; }
            .gate-pill { display: inline-block; border: 1px solid #e0a23b; color: #b46b00; background: #fff5e5; border-radius: 999px; padding: 5px 14px; font-size: 12px; font-weight: 900; }
            .action-row { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 10px; }
            .primary-btn, .outline-btn, .followup-btn, .panel-tab { border-radius: 6px; font-weight: 850; cursor: pointer; }
            .primary-btn { min-height: 40px; padding: 0 20px; color: white; background: #0647b7; border: 1px solid #0647b7; }
            .outline-btn { min-height: 40px; padding: 0 20px; color: #0647b7; background: white; border: 1px solid #0647b7; }
            .followup-title { margin: 30px 0 10px; font-weight: 850; }
            .followup-row { display: flex; flex-wrap: wrap; gap: 12px; }
            .followup-btn { padding: 8px 16px; color: #0647b7; background: white; border: 1px solid #b9c8dc; border-radius: 999px; }
            .ask-footer { margin-top: 14px; display: flex; gap: 10px; }
            .artifact-tabs { display: flex; align-items: center; gap: 48px; border-bottom: 1px solid #d9e2ef; padding: 22px 30px 0; height: 82px; }
            .panel-tab { height: 42px; padding: 0 13px; border: 0; background: white; color: #17242f; font-size: 16px; position: relative; }
            .panel-tab.active { color: #0647b7; }
            .panel-tab.active::after { content: ""; position: absolute; left: 8px; right: 8px; bottom: -1px; height: 4px; background: #0647b7; }
            .preview-note { margin-left: auto; border: 1px solid #87c99a; background: #eaf7ee; color: #15803d; border-radius: 999px; padding: 8px 16px; font-size: 12px; font-weight: 850; }
            .artifact-stack { height: calc(100% - 82px); overflow-y: auto; padding: 22px 38px 38px; }
            .artifact-card { border: 1px solid #d9e2ef; border-radius: 8px; background: white; padding: 18px 24px 22px; margin-bottom: 18px; }
            .artifact-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
            .artifact-title { font-size: 18px; font-weight: 850; }
            .latest { border: 1px solid #87c99a; background: #eaf7ee; color: #15803d; border-radius: 999px; padding: 5px 13px; font-size: 12px; font-weight: 850; }
            .code-box { background: #f8fbff; border: 1px solid #d9e2ef; padding: 16px 18px; margin: 0; color: #17242f; font-family: Consolas, Menlo, monospace; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
            .studio-placeholder, .command-placeholder, .dashboard-grid, .preview-card { padding: 32px; }
            .workspace-title { font-size: 28px; color: #063f8f; font-weight: 850; margin: 0 0 10px; }
            .muted { color: #5b6b7a; }
            """
    )


def top_bar(state: AskState) -> html.Div:
    def tab(label: str, workspace: str) -> html.Button:
        cls = "workspace-tab active" if state.workspace == workspace else "workspace-tab"
        return html.Button(label, id=f"nav-{workspace}", className=cls)

    return html.Div(
        [
            html.Div("OXY", className="brand-mark"),
            html.Div([html.Div("MAX Agent", className="brand-title"), html.Div("Governed preventive-maintenance strategy copilot for Oxy", className="brand-sub")]),
            html.Div([tab("Command Center", "command"), tab("Ask MAX", "ask"), tab("Work Strategy Studio", "studio")], className="top-tabs"),
            html.Div([html.Span(className="status-dot"), html.Span("Synthetic Data")], className="right-status"),
            html.Div("SG", className="avatar"),
        ],
        className="topbar",
    )


def context_row(state: AskState) -> html.Div:
    asset_label = state.resolved_asset or "Fleet scope"
    chips = [
        ("Asset", asset_label),
        ("Plant", "Houston"),
        ("Class", "Centrifugal Pump"),
        ("Time window", "Last 24 Months"),
        ("BU profile", "default_oxy"),
    ]
    return html.Div(
        [
            html.Div([html.Span(label, className="label"), html.Span(value, className="value")], className="context-chip")
            for label, value in chips
        ]
        + [html.Div("A Synthetic", className="context-chip synthetic-chip")],
        className="context-row",
    )


def pm_health_figure() -> go.Figure:
    fig = go.Figure()
    fig.add_bar(
        x=["PASS", "REVIEW", "BLOCKED", "DRAFT"],
        y=[24, 41, 28, 15],
        marker_color=[COLORS["green"], COLORS["orange"], COLORS["red"], COLORS["active"]],
        hoverinfo="skip",
    )
    fig.add_scatter(x=["BLOCKED"], y=[25], mode="markers", marker={"size": 15, "color": "white", "line": {"color": COLORS["red"], "width": 4}}, hoverinfo="skip")
    fig.update_layout(
        height=210,
        margin={"l": 36, "r": 18, "t": 10, "b": 32},
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis={"showgrid": False, "zeroline": False, "tickfont": {"color": COLORS["muted"]}},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
    )
    return fig


def comparison_figure() -> go.Figure:
    fig = go.Figure()
    fig.add_box(y=[0.22, 0.31, 0.45, 0.72, 1.1, 1.8, 2.4], x=["Cohort"] * 7, name="Cohort", marker_color="#7aa7e8", hoverinfo="skip")
    fig.add_scatter(x=["Median"], y=[0.9], mode="markers", marker={"size": 12, "color": "#7aa7e8"}, hoverinfo="skip")
    fig.add_scatter(x=["PUMP-4110"], y=[1.45], mode="markers", marker={"size": 18, "color": COLORS["red"]}, hoverinfo="skip")
    fig.update_layout(
        height=230,
        margin={"l": 36, "r": 18, "t": 8, "b": 38},
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis={"showgrid": False, "zeroline": False, "tickfont": {"color": COLORS["muted"]}},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False, "type": "log"},
    )
    return fig


def dashboard_figure() -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=["Mandatory PM coverage", "CBM evidence missing", "Criticality not validated", "Out of scope"],
                y=[6, 5, 3, 2],
                marker_color=[COLORS["red"], COLORS["orange"], "#6b7a90", COLORS["active"]],
            )
        ]
    )
    fig.update_layout(
        height=280,
        margin={"l": 40, "r": 16, "t": 12, "b": 70},
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        yaxis={"showgrid": True, "gridcolor": "#edf2f7", "zeroline": False},
        xaxis={"tickangle": -16},
    )
    return fig


def evidence_table() -> dash_table.DataTable:
    return dash_table.DataTable(
        columns=[
            {"name": "Signal", "id": "signal"},
            {"name": "Available", "id": "available"},
            {"name": "Coverage", "id": "coverage"},
            {"name": "Recency", "id": "recency"},
            {"name": "Status", "id": "status"},
        ],
        data=[
            {"signal": "Vibration trend", "available": "1 / 3", "coverage": "33%", "recency": "Stale", "status": "Gap"},
            {"signal": "Oil analysis", "available": "0 / 1", "coverage": "0%", "recency": "Missing", "status": "Gap"},
            {"signal": "Work orders", "available": "18", "coverage": "100%", "recency": "7 days", "status": "Ready"},
        ],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#f8fbff", "fontWeight": "800", "color": COLORS["muted"], "border": f"1px solid {COLORS['line']}"},
        style_cell={"fontFamily": FONT, "fontSize": "14px", "padding": "10px 12px", "border": f"1px solid {COLORS['line']}", "textAlign": "left"},
        style_data_conditional=[
            {"if": {"filter_query": "{status} = Gap", "column_id": "status"}, "color": COLORS["red"], "fontWeight": "800"},
            {"if": {"filter_query": "{status} = Ready", "column_id": "status"}, "color": COLORS["green"], "fontWeight": "800"},
        ],
    )


def gate_table() -> dash_table.DataTable:
    return dash_table.DataTable(
        columns=[{"name": "Field", "id": "field"}, {"name": "Value", "id": "value"}],
        data=[
            {"field": "gate_status", "value": "REVIEW_REQUIRED"},
            {"field": "reason_code", "value": "RISK_REVIEW_REQUIRED"},
            {"field": "blocked_action", "value": "DIRECT_SAP_UPDATE"},
            {"field": "allowed_action", "value": "DRAFT_FOR_REVIEW"},
        ],
        style_header={"backgroundColor": "#f8fbff", "fontWeight": "800", "color": COLORS["muted"], "border": f"1px solid {COLORS['line']}"},
        style_cell={"fontFamily": "Consolas, Menlo, monospace", "fontSize": "13px", "padding": "9px 12px", "border": f"1px solid {COLORS['line']}", "textAlign": "left"},
        style_data_conditional=[{"if": {"filter_query": "{value} = REVIEW_REQUIRED", "column_id": "value"}, "color": COLORS["orange_text"], "fontWeight": "900"}],
    )


def artifact_card(title: str, child: Any) -> html.Div:
    return html.Div(
        [
            html.Div([html.Div(title, className="artifact-title"), html.Div("Latest", className="latest")], className="artifact-head"),
            child,
        ],
        className="artifact-card",
    )


def artifacts_panel() -> html.Div:
    return html.Div(
        [
            artifact_card("1. PM Health Chart", dcc.Graph(figure=pm_health_figure(), config={"displayModeBar": False})),
            artifact_card("2. Evidence Table", evidence_table()),
            artifact_card("3. Comparison Cohort", dcc.Graph(figure=comparison_figure(), config={"displayModeBar": False})),
            artifact_card(
                "4. SQL / Genie",
                html.Pre("SELECT asset_id, gate_status, reason_code\nFROM pm_gate\nWHERE asset_id = 'PUMP-4110';", className="code-box"),
            ),
            artifact_card("5. Gate Trace", gate_table()),
        ],
        className="artifact-stack",
    )


def dashboard_panel() -> html.Div:
    return html.Div(
        [
            html.H2("Dashboard", className="workspace-title"),
            html.Div("Fleet-level dashboard view. This is broader than the artifact stack and can be opened from the chat action.", className="muted"),
            html.Div(
                [
                    html.Div([html.Div("Gate reason mix", className="artifact-title"), dcc.Graph(figure=dashboard_figure(), config={"displayModeBar": False})], className="artifact-card"),
                    html.Div(
                        [
                            html.Div("Queue slices", className="artifact-title"),
                            dash_table.DataTable(
                                columns=[
                                    {"name": "Slice", "id": "slice"},
                                    {"name": "Count", "id": "count"},
                                    {"name": "First action", "id": "action"},
                                ],
                                data=[
                                    {"slice": "Blocked", "count": 6, "action": "Resolve reason code"},
                                    {"slice": "Review Required", "count": 5, "action": "Open Studio"},
                                    {"slice": "Draft Only", "count": 2, "action": "Gather approver"},
                                ],
                                style_cell={"fontFamily": FONT, "fontSize": "14px", "padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "800", "backgroundColor": "#f8fbff"},
                            ),
                        ],
                        className="artifact-card",
                    ),
                ],
                className="dashboard-grid",
            ),
        ],
        className="artifact-stack",
    )


def preview_panel(asset: str) -> html.Div:
    return html.Div(
        [
            html.H2(f"{asset} Preview", className="workspace-title"),
            html.Div("PM preview appears only because the chat resolved a specific PM/equipment context.", className="muted"),
            html.Div(
                [
                    html.Div("Classification", className="artifact-title"),
                    html.Div("Missing Evidence", className="gate-pill", style={"marginTop": "12px"}),
                    html.P("Gate: REVIEW_REQUIRED", style={"fontWeight": 800}),
                    html.P("Reason code: RISK_REVIEW_REQUIRED"),
                    html.P("Allowed action: Draft for planner / reliability engineer review."),
                    html.P("Blocked action: Direct SAP update or unattended PM reduction."),
                    html.Div([html.Button("Open in Studio", id="preview-open-studio", className="primary-btn")], className="action-row"),
                ],
                className="artifact-card preview-card",
            ),
        ],
        className="artifact-stack",
    )


def right_panel(state: AskState) -> html.Div:
    def panel_button(label: str, panel: str) -> html.Button:
        cls = "panel-tab active" if state.panel == panel else "panel-tab"
        return html.Button(label, id=f"panel-{panel}", className=cls)

    panel = state.panel
    if panel == "preview" and not state.has_preview:
        panel = "artifacts"

    if panel == "dashboard":
        body = dashboard_panel()
    elif panel == "preview" and state.has_preview:
        body = preview_panel(state.resolved_asset or "Selected PM")
    else:
        body = artifacts_panel()

    tabs = [panel_button("Artifacts", "artifacts"), panel_button("Dashboard", "dashboard")]
    if state.has_preview:
        tabs.append(panel_button("Preview", "preview"))

    return html.Div(
        [
            html.Div(
                tabs + ([html.Div(f"Preview available: {state.resolved_asset} context", className="preview-note")] if state.has_preview else []),
                className="artifact-tabs",
            ),
            body,
        ],
        className="pane",
    )


def response_text(state: AskState) -> tuple[list[str], list[tuple[str, str]], bool]:
    if state.has_preview:
        overview = [
            f"{state.resolved_asset} is in a review-required state. MAX should not auto-change SAP.",
            "The PM is not yet classifiable by Oxy governance as safe to reduce or retire.",
            "Evidence points to higher failure frequency and incomplete CBM coverage.",
        ]
        insights = [
            ("PM Health chart:", "PUMP-4110 sits in the review-required band."),
            ("Evidence table:", "Vibration trend is incomplete; oil analysis is missing."),
            ("Comparison:", "Similar pumps with fuller CBM coverage show lower risk."),
            ("Oxy context:", "Mandatory/governed PM changes require human review."),
        ]
        return overview, insights, True
    overview = [
        "This is a fleet-level question, so MAX shows fleet artifacts and dashboard actions.",
        "No single PM or equipment record was resolved from the prompt.",
        "Preview stays hidden until the conversation resolves a specific asset or PM.",
    ]
    insights = [
        ("Gate distribution:", "Blocked and review-required items are concentrated in the pump queue."),
        ("Reason codes:", "Missing CBM evidence and mandatory PM coverage dominate."),
        ("Oxy context:", "This queue is for governed review, not auto-change."),
    ]
    return overview, insights, False


def chat_panel(state: AskState) -> html.Div:
    overview, insights, has_preview = response_text(state)
    action_buttons = [
        html.Button("Open Dashboard", id="action-dashboard", className="outline-btn"),
    ]
    if has_preview:
        action_buttons.insert(0, html.Button("Open in Studio", id="action-studio", className="primary-btn"))
        action_buttons.append(html.Button("Open Preview", id="action-preview", className="outline-btn"))

    followups = [
        "What evidence is missing?",
        "Compare with PUMP-4102",
        "What can we approve?",
    ] if has_preview else [
        "Show only blocked PMs",
        "Which reasons dominate?",
        "Pick a PM to preview",
    ]

    return html.Div(
        [
            html.Div(
                [
                    dcc.Input(id="ask-input", value=state.query, debounce=False, className="ask-input"),
                    html.Button(">", id="ask-send", className="send-btn"),
                ],
                className="ask-row",
            ),
            html.Div(
                [
                    html.Div("MAX", className="max-dot"),
                    html.Div("Thinking", style={"fontWeight": 850}),
                    html.Div([html.Span(className="step-dot"), "Running tools"]),
                    html.Div([html.Span(className="step-dot"), "Building artifacts"]),
                    html.Div([html.Span(className="step-dot", style={"background": COLORS["active"]}), "Composing answer"]),
                ],
                className="progress",
            ),
            html.Div(
                [
                    html.Span("Tools in use", className="muted"),
                    *[html.Span(label, className="tool-pill") for label in ["PM Classification", "Work Orders", "Comparison", "Oxy Gate", "Genie"]],
                ],
                className="tool-row",
            ),
            html.Div(
                [
                    html.H2("Overview", className="section-title"),
                    *[html.P(line) for line in overview],
                    html.H2("Key Insights", className="section-title", style={"marginTop": "28px"}),
                    html.Ul([html.Li([html.Strong(k + " "), v]) for k, v in insights]),
                    html.H2("Recommendation and Governance", className="section-title"),
                    html.P([html.Strong("Gate: "), html.Span("REVIEW REQUIRED" if has_preview else "REVIEW QUEUE", className="gate-pill")]),
                    html.P([html.Strong("Allowed action: ", style={"color": COLORS["green"]}), "Draft package for planner / reliability engineer review." if has_preview else "Filter queue and select a PM for governed review."]),
                    html.P([html.Strong("Blocked action: ", style={"color": COLORS["red"]}), "Direct SAP update or unattended PM reduction."]),
                    html.H2("Actions", className="section-title", style={"marginTop": "26px"}),
                    html.Div(action_buttons, className="action-row"),
                ],
                className="chat-card",
            ),
            html.Div("MAX suggested follow-ups", className="followup-title"),
            html.Div(
                [html.Button(label, id={"type": "followup", "label": label}, className="followup-btn") for label in followups],
                className="followup-row",
            ),
            html.Div(
                [
                    dcc.Input(id="ask-followup-input", placeholder="Ask a follow-up question...", debounce=False, className="ask-input"),
                    html.Button(">", id="ask-followup-send", className="send-btn"),
                ],
                className="ask-footer",
            ),
        ],
        className="pane-scroll",
    )


def ask_workspace(state: AskState) -> html.Div:
    return html.Div([html.Div(chat_panel(state), className="pane"), right_panel(state)], className="main-grid")


def placeholder_workspace(state: AskState, workspace: str) -> html.Div:
    if workspace == "command":
        title = "Command Center"
        body = "Landing queue: priority tiles filter the PM Health table. Selecting a row opens PM preview; blue PM link opens Studio."
        cls = "command-placeholder"
    else:
        title = "Work Strategy Studio"
        body = f"Governed PM review workspace for {state.resolved_asset or 'the selected PM'}: filters, evidence, comparison, gate, SAP package, approval state, and tool trace."
        cls = "studio-placeholder"
    return html.Div(
        [
            html.Div(
                [
                    html.H1(title, className="workspace-title"),
                    html.P(body, className="muted"),
                    html.Div([html.Button("Back to Ask MAX", id="back-ask", className="primary-btn")], className="action-row"),
                ],
                className=f"pane {cls}",
            )
        ],
        style={"padding": "18px 22px"},
    )


def layout_from_state(state: AskState) -> html.Div:
    body = ask_workspace(state) if state.workspace == "ask" else placeholder_workspace(state, state.workspace)
    return html.Div([top_bar(state), context_row(state), body], className="app-shell")


app = Dash(__name__, title="MAX Ask Prototype", suppress_callback_exceptions=True)
app.index_string = (
    "<!DOCTYPE html><html><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}"
    "<style>"
    + css_text()
    + "</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"
)
app.layout = html.Div([dcc.Store(id="ui-state", data=AskState().as_dict()), html.Div(id="prototype-root")])


@app.callback(Output("prototype-root", "children"), Input("ui-state", "data"))
def render(data: dict[str, Any] | None):
    return layout_from_state(AskState.from_dict(data))


@app.callback(
    Output("ui-state", "data"),
    Input("ask-send", "n_clicks", allow_optional=True),
    Input("ask-input", "n_submit", allow_optional=True),
    Input("action-dashboard", "n_clicks", allow_optional=True),
    Input("action-preview", "n_clicks", allow_optional=True),
    Input("action-studio", "n_clicks", allow_optional=True),
    Input("preview-open-studio", "n_clicks", allow_optional=True),
    Input("panel-artifacts", "n_clicks", allow_optional=True),
    Input("panel-dashboard", "n_clicks", allow_optional=True),
    Input("panel-preview", "n_clicks", allow_optional=True),
    Input("nav-command", "n_clicks", allow_optional=True),
    Input("nav-ask", "n_clicks", allow_optional=True),
    Input("nav-studio", "n_clicks", allow_optional=True),
    Input("back-ask", "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "What evidence is missing?"}, "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "Compare with PUMP-4102"}, "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "What can we approve?"}, "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "Show only blocked PMs"}, "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "Which reasons dominate?"}, "n_clicks", allow_optional=True),
    Input({"type": "followup", "label": "Pick a PM to preview"}, "n_clicks", allow_optional=True),
    State("ask-input", "value"),
    State("ui-state", "data"),
    prevent_initial_call=True,
)
def update_state(*values):
    triggered = callback_context.triggered_id
    ask_value = values[-2]
    state = AskState.from_dict(values[-1])
    if not triggered:
        return no_update

    if triggered in ("ask-send", "ask-input"):
        query = (ask_value or "").strip() or state.query
        return AskState(workspace="ask", panel="artifacts", query=query, resolved_asset=resolve_asset(query)).as_dict()

    if isinstance(triggered, dict) and triggered.get("type") == "followup":
        label = triggered.get("label", "")
        query = label
        if label == "Pick a PM to preview":
            query = "Show preview for PUMP-4110"
        return AskState(workspace="ask", panel="artifacts", query=query, resolved_asset=resolve_asset(query) or state.resolved_asset).as_dict()

    if triggered == "action-dashboard" or triggered == "panel-dashboard":
        return AskState(workspace="ask", panel="dashboard", query=state.query, resolved_asset=state.resolved_asset).as_dict()
    if triggered == "action-preview" or triggered == "panel-preview":
        panel = "preview" if state.has_preview else "artifacts"
        return AskState(workspace="ask", panel=panel, query=state.query, resolved_asset=state.resolved_asset).as_dict()
    if triggered == "panel-artifacts":
        return AskState(workspace="ask", panel="artifacts", query=state.query, resolved_asset=state.resolved_asset).as_dict()
    if triggered in ("action-studio", "preview-open-studio", "nav-studio"):
        return AskState(workspace="studio", panel=state.panel, query=state.query, resolved_asset=state.resolved_asset).as_dict()
    if triggered == "nav-command":
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=state.resolved_asset).as_dict()
    if triggered in ("nav-ask", "back-ask"):
        return AskState(workspace="ask", panel=state.panel, query=state.query, resolved_asset=state.resolved_asset).as_dict()

    return state.as_dict()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8061"))
    app.run(host="127.0.0.1", port=port, debug=False)
