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
import json
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update


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
    queue_filter: str = "all"
    preview_asset: str | None = None
    studio_variant: str = "b"

    @property
    def has_preview(self) -> bool:
        return bool(self.resolved_asset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "panel": self.panel,
            "query": self.query,
            "resolved_asset": self.resolved_asset,
            "queue_filter": self.queue_filter,
            "preview_asset": self.preview_asset,
            "studio_variant": self.studio_variant,
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
            queue_filter=value.get("queue_filter") or "all",
            preview_asset=value.get("preview_asset"),
            studio_variant=value.get("studio_variant") or "b",
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


def current_triggered_id() -> Any:
    """Return Dash triggered_id, including decoded dict IDs for pattern-matching callbacks."""
    triggered = callback_context.triggered_id
    if isinstance(triggered, dict) or triggered is None:
        return triggered
    raw = (callback_context.triggered or [{}])[0].get("prop_id", "").rsplit(".", 1)[0]
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return triggered
    return triggered


QUEUE_ROWS = [
    {"asset": "COMP-2201", "pm": "PM-COMP-2201-A", "crit": "3", "label": "Governance Review Required", "gate": "BLOCKED", "reason": "MANDATORY_PM_CANNOT_REDUCE_COVERAGE", "next": "Keep PM, governance review", "filter": "blocked"},
    {"asset": "VALVE-3301", "pm": "PM-VALVE-3301-A", "crit": "4", "label": "Governance Review Required", "gate": "BLOCKED", "reason": "MANDATORY_PM_CANNOT_REDUCE_COVERAGE", "next": "Keep PM, governance review", "filter": "blocked"},
    {"asset": "PUMP-4115", "pm": "PM-PUMP-4115-A", "crit": "2", "label": "Governance Review Required", "gate": "BLOCKED", "reason": "CBM_REQUIRES_REAL_MEASUREMENT_READINGS", "next": "Collect CBM readings", "filter": "blocked"},
    {"asset": "PUMP-4120", "pm": "PM-PUMP-4120-A", "crit": "3", "label": "Governance Review Required", "gate": "BLOCKED", "reason": "RTF_BARRED_FOR_CRITICAL_2_3_4", "next": "No RTF, escalate", "filter": "blocked"},
    {"asset": "PUMP-4110", "pm": "PM-PUMP-4110-A", "crit": "2", "label": "Missing Evidence", "gate": "REVIEW_REQUIRED", "reason": "RISK_REVIEW_REQUIRED", "next": "Draft review package", "filter": "review"},
    {"asset": "HX-6601", "pm": "PM-HX-6601-A", "crit": "0", "label": "Missing Evidence", "gate": "REVIEW_REQUIRED", "reason": "CRITICALITY_NOT_VALIDATED", "next": "Validate criticality", "filter": "review"},
    {"asset": "PUMP-4116", "pm": "PM-PUMP-4116-A", "crit": "1", "label": "Missing Evidence", "gate": "DRAFT_ONLY", "reason": "CBM_SYNTHETIC_DEMO_ONLY", "next": "Demo draft only", "filter": "draft"},
    {"asset": "MOTOR-5501", "pm": "PM-MOTOR-5501-A", "crit": "1", "label": "Missing Evidence", "gate": "DRAFT_ONLY", "reason": "WORK_STRATEGY_OWNER_REQUIRED", "next": "Assign WSO", "filter": "draft"},
    {"asset": "PUMP-4140", "pm": "PM-PUMP-4140-A", "crit": "1", "label": "Not classified", "gate": "BLOCKED", "reason": "EXEMPT_ASSET_OUT_OF_SCOPE", "next": "No action", "filter": "blocked"},
    {"asset": "FAN-7701", "pm": "PM-FAN-7701-A", "crit": "1", "label": "Missing Evidence", "gate": "REVIEW_REQUIRED", "reason": "CRITICALITY_OR_STRATEGY_CHANGE", "next": "Review with reliability", "filter": "review"},
]

PRIORITY_TILES = [
    ("blocked", "Blocked", 5, "Cannot proceed without governance/data resolution"),
    ("review", "Review Required", 3, "Human decision needed before package movement"),
    ("draft", "Draft Only", 2, "Draft package allowed, no master data write"),
    ("missing", "Missing Evidence", 5, "Evidence gaps block confident strategy scoring"),
    ("readiness", "Data Readiness", 3, "Readiness gaps to close before execution"),
]


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
            .dashboard-grid, .preview-card { padding: 32px; }
            .workspace-title { font-size: 28px; color: #063f8f; font-weight: 850; margin: 0 0 10px; }
            .muted { color: #5b6b7a; }
            .command-wrap { padding: 18px 22px 24px; height: calc(100vh - 139px); min-height: 760px; }
            .command-grid { height: 100%; display: grid; grid-template-columns: 290px minmax(680px, 1fr); gap: 18px; }
            .command-grid.with-preview { grid-template-columns: 290px minmax(580px, 1fr) 360px; }
            .panel-pad { padding: 22px; }
            .panel-title { font-size: 22px; font-weight: 850; color: #17242f; margin: 0 0 8px; }
            .priority-tile { width: 100%; text-align: left; border: 1px solid #d9e2ef; background: white; border-radius: 8px; padding: 14px 14px; margin-top: 10px; cursor: pointer; }
            .priority-tile.active { border-color: #0647b7; box-shadow: inset 4px 0 0 #0647b7; background: #f7fbff; }
            .tile-row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
            .tile-label { font-weight: 850; color: #17242f; }
            .tile-count { color: #0647b7; font-size: 22px; font-weight: 900; }
            .tile-note { color: #5b6b7a; font-size: 12px; margin-top: 4px; line-height: 1.35; }
            .queue-header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 14px; }
            .queue-filter-row { display: grid; grid-template-columns: 1.1fr 1fr 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 10px; }
            .mini-filter { border: 1px solid #d9e2ef; background: #f8fbff; color: #5b6b7a; border-radius: 6px; padding: 7px 9px; font-size: 12px; }
            .queue-table { width: 100%; border-collapse: collapse; }
            .queue-table th { text-align: left; color: #5b6b7a; font-size: 12px; padding: 9px 10px; border-bottom: 1px solid #d9e2ef; background: #f8fbff; }
            .queue-table td { padding: 10px; border-bottom: 1px solid #d9e2ef; font-size: 13px; vertical-align: middle; }
            .link-btn { border: 0; background: transparent; color: #0647b7; font-weight: 850; padding: 0; cursor: pointer; }
            .ghost-btn { border: 1px solid #b9c8dc; color: #0647b7; background: white; border-radius: 6px; padding: 7px 10px; font-size: 12px; font-weight: 850; cursor: pointer; }
            .gate { display: inline-block; min-width: 86px; text-align: center; color: white; border-radius: 4px; padding: 5px 7px; font-size: 11px; font-weight: 850; }
            .gate.blocked { background: #c1261b; }
            .gate.review { background: #b7791f; }
            .gate.draft { background: #0647b7; }
            .preview-rail { padding: 20px; }
            .preview-kicker { color: #5b6b7a; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; }
            .preview-title { color: #063f8f; font-size: 24px; font-weight: 900; margin: 8px 0 12px; }
            .reason-box { border: 1px solid #d9e2ef; border-radius: 8px; padding: 12px; background: #f8fbff; margin: 12px 0; }
            .studio-wrap { padding: 18px 22px 24px; height: calc(100vh - 139px); min-height: 760px; }
            .studio-page { height: 100%; display: flex; flex-direction: column; gap: 14px; min-height: 0; }
            .studio-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }
            .studio-options { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
            .studio-option-btn { border: 1px solid #b9c8dc; color: #0647b7; background: white; border-radius: 7px; padding: 8px 12px; font-size: 12px; font-weight: 900; cursor: pointer; }
            .studio-option-btn.active { color: white; background: #0647b7; border-color: #0647b7; }
            .studio-body { flex: 1; min-height: 0; }
            .studio-grid { display: grid; grid-template-columns: minmax(310px, .82fr) minmax(430px, 1.12fr) minmax(320px, .8fr); gap: 18px; height: 100%; }
            .studio-grid-b { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 18px; height: 100%; }
            .studio-b-lower { display: grid; grid-template-columns: minmax(420px, 1fr) minmax(520px, 1.2fr); gap: 18px; min-height: 0; }
            .studio-grid-c { display: grid; grid-template-columns: minmax(420px, 1.1fr) minmax(360px, .9fr) minmax(320px, .75fr); gap: 18px; height: 100%; }
            .studio-scroll { height: 100%; overflow-y: auto; }
            .summary-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 12px 0 16px; }
            .metric-tile { border: 1px solid #d9e2ef; border-radius: 8px; padding: 12px; background: #f8fbff; }
            .metric-label { color: #5b6b7a; font-size: 12px; }
            .metric-value { color: #17242f; font-size: 16px; font-weight: 900; margin-top: 3px; }
            .recommendation-card { border: 2px solid #0647b7; border-radius: 9px; padding: 18px; background: #fbfdff; margin-bottom: 14px; }
            .hero-recommendation { border: 2px solid #0647b7; border-radius: 10px; background: #fbfdff; padding: 20px 22px; display: grid; grid-template-columns: minmax(460px, 1.2fr) minmax(300px, .8fr); gap: 18px; align-items: center; }
            .hero-title { margin: 5px 0 8px; color: #063f8f; font-size: 24px; font-weight: 900; }
            .draft-card { border: 1px solid #d9e2ef; border-radius: 9px; padding: 16px; background: white; margin-bottom: 14px; }
            .draft-badge { display: inline-block; border: 1px solid #0647b7; background: #eaf1ff; color: #0647b7; border-radius: 999px; padding: 5px 12px; font-size: 12px; font-weight: 900; }
            .draft-editor { border: 2px solid #0647b7; border-radius: 10px; background: #fbfdff; padding: 18px; margin-bottom: 14px; }
            .draft-field { border: 1px solid #d9e2ef; border-radius: 8px; background: white; padding: 12px; margin-top: 10px; }
            .field-label { color: #5b6b7a; font-size: 12px; font-weight: 850; margin-bottom: 5px; }
            .field-value { color: #17242f; font-weight: 800; line-height: 1.4; }
            .step-list { display: grid; gap: 10px; margin-top: 12px; }
            .step-item { display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: start; }
            .step-num { width: 28px; height: 28px; border-radius: 50%; background: #eaf1ff; color: #0647b7; display: grid; place-items: center; font-weight: 900; font-size: 12px; }
            .sap-action-list { margin: 8px 0 0; padding-left: 20px; }
            .sap-action-list li { margin: 8px 0; }
            details.collapse-card { border: 1px solid #d9e2ef; border-radius: 9px; background: white; margin-bottom: 12px; }
            details.collapse-card summary { cursor: pointer; padding: 15px 16px; font-weight: 900; color: #17242f; }
            details.collapse-card > div { padding: 0 16px 16px; }
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


def _gate_class(gate: str) -> str:
    if gate == "BLOCKED":
        return "gate blocked"
    if gate == "DRAFT_ONLY":
        return "gate draft"
    return "gate review"


def _filtered_queue(state: AskState) -> list[dict[str, str]]:
    if state.queue_filter == "all":
        return QUEUE_ROWS
    if state.queue_filter == "missing":
        return [r for r in QUEUE_ROWS if "Missing" in r["label"]]
    if state.queue_filter == "readiness":
        return [r for r in QUEUE_ROWS if "CBM" in r["reason"] or "CRITICALITY" in r["reason"] or "OWNER" in r["reason"]]
    return [r for r in QUEUE_ROWS if r["filter"] == state.queue_filter]


def command_center_workspace(state: AskState) -> html.Div:
    rows = _filtered_queue(state)
    preview_asset = state.preview_asset or state.resolved_asset
    preview_row = next((r for r in QUEUE_ROWS if r["asset"] == preview_asset), None)
    grid_class = "command-grid with-preview" if preview_row else "command-grid"

    priority_panel = html.Div(
        [
            html.H2("Review Priorities", className="panel-title"),
            html.Div("Click a tile to filter the PM Health queue. No expand/collapse here.", className="muted"),
            html.Button("All queue items", id="priority-all", className=f"priority-tile {'active' if state.queue_filter == 'all' else ''}"),
            *[
                html.Button(
                    [
                        html.Div([html.Span(label, className="tile-label"), html.Span(str(count), className="tile-count")], className="tile-row"),
                        html.Div(note, className="tile-note"),
                    ],
                    id=f"priority-{value}",
                    className=f"priority-tile {'active' if state.queue_filter == value else ''}",
                )
                for value, label, count, note in PRIORITY_TILES
            ],
        ],
        className="pane panel-pad",
    )

    table = html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Asset"),
                        html.Th("PM"),
                        html.Th("Label"),
                        html.Th("Gate"),
                        html.Th("Recommended Next Action"),
                        html.Th("Reason"),
                        html.Th("Preview"),
                    ]
                )
            ),
            html.Tbody(
                [
                    html.Tr(
                        [
                            html.Td(html.Button(r["asset"], id=f"pm-studio-{r['asset']}", className="link-btn")),
                            html.Td(r["pm"]),
                            html.Td(r["label"]),
                            html.Td(html.Span(r["gate"], className=_gate_class(r["gate"]))),
                            html.Td(r["next"]),
                            html.Td(r["reason"]),
                            html.Td(html.Button("Open", id=f"pm-preview-{r['asset']}", className="ghost-btn")),
                        ]
                    )
                    for r in rows
                ]
            ),
        ],
        className="queue-table",
    )

    queue_panel = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("PM Health Review Queue", className="panel-title"),
                            html.Div("Highest-attention PMs first. Blue asset links open Studio directly; Open shows a preview rail.", className="muted"),
                        ]
                    ),
                    html.Div(f"{len(rows)} rows", className="latest"),
                ],
                className="queue-header",
            ),
            html.Div(
                [
                    html.Div("Asset filter", className="mini-filter"),
                    html.Div("PM filter", className="mini-filter"),
                    html.Div("Label filter", className="mini-filter"),
                    html.Div("Gate filter", className="mini-filter"),
                    html.Div("Reason filter", className="mini-filter"),
                ],
                className="queue-filter-row",
            ),
            table,
        ],
        className="pane panel-pad",
    )

    preview_panel = html.Div()
    if preview_row:
        preview_panel = html.Div(
            [
                html.Div("Selected PM preview", className="preview-kicker"),
                html.Div(preview_row["asset"], className="preview-title"),
                html.Div(preview_row["pm"], style={"fontWeight": 850}),
                html.Div(
                    [
                        html.Div([html.Strong("Classification: "), preview_row["label"]]),
                        html.Div([html.Strong("Gate: "), html.Span(preview_row["gate"], className=_gate_class(preview_row["gate"]))], style={"marginTop": "8px"}),
                        html.Div([html.Strong("Reason: "), preview_row["reason"]], style={"marginTop": "8px"}),
                    ],
                    className="reason-box",
                ),
                html.P("Oxy context: this is a governed review queue. MAX may draft a package, but cannot write SAP or reduce mandatory coverage without human approval.", className="muted"),
                html.Div(
                    [
                        html.Button("Ask MAX about this PM", id="command-preview-ask", className="primary-btn"),
                        html.Button("Open in Studio", id="command-preview-studio", className="outline-btn"),
                    ],
                    className="action-row",
                ),
            ],
            className="pane preview-rail",
        )

    return html.Div([html.Div([priority_panel, queue_panel, preview_panel], className=grid_class)], className="command-wrap")


def studio_workspace(state: AskState) -> html.Div:
    asset = state.resolved_asset or state.preview_asset or "PUMP-4110"
    why_items = [
        ("Evidence gap", "Vibration trend is incomplete and oil analysis is missing."),
        ("Comparison signal", "Similar pumps with fuller CBM coverage show lower risk."),
        ("Oxy governance", "Mandatory / criticality-protected PM changes require review."),
        ("Gate", "REVIEW_REQUIRED: draft is allowed, direct SAP write-back is blocked."),
    ]
    sap_actions = [
        "Create draft package PKG-PUMP-4110-STRAT-001.",
        "Keep existing time-based PM active while evidence is remediated.",
        "Add CBM measurement-point readiness task for vibration route.",
        "Route to Planner and Reliability Engineer; no unattended SAP update.",
    ]

    def option_button(value: str, label: str) -> html.Button:
        active = state.studio_variant == value
        return html.Button(label, id=f"studio-option-{value}", className=f"studio-option-btn {'active' if active else ''}")

    header = html.Div(
        [
            html.Div(
                [
                    html.H1("Work Strategy Studio", className="workspace-title"),
                    html.Div(f"{asset} | Centrifugal Pump | Houston | Last 24 Months", className="muted"),
                ]
            ),
            html.Div(
                [
                    option_button("a", "Option A: Decision Canvas"),
                    option_button("b", "Option B: Recommendation First"),
                    option_button("c", "Option C: Draft Workbench"),
                ],
                className="studio-options",
            ),
        ],
        className="studio-header",
    )

    option_a = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.Div("Gate", className="metric-label"), html.Div("REVIEW_REQUIRED", className="metric-value")], className="metric-tile"),
                            html.Div([html.Div("Package", className="metric-label"), html.Div("DRAFT", className="metric-value")], className="metric-tile"),
                            html.Div([html.Div("SAP write-back", className="metric-label"), html.Div("BLOCKED", className="metric-value")], className="metric-tile"),
                        ],
                        className="summary-strip",
                    ),
                    html.H2("Why MAX Recommended This", className="panel-title"),
                    *[
                        html.Div([html.Div(label, className="artifact-title"), html.P(body, className="muted")], className="artifact-card")
                        for label, body in why_items
                    ],
                ],
                className="pane panel-pad studio-scroll",
            ),
            html.Div(
                [
                    html.H2("MAX Recommendation", className="panel-title"),
                    html.Div(
                        [
                            html.Div("Recommended strategy", className="preview-kicker"),
                            html.H3("Draft a governed review package; do not reduce or retire the PM yet.", style={"margin": "8px 0 10px", "color": COLORS["oxy"]}),
                            html.P("MAX recommends evidence remediation plus a planner / reliability engineer review before any SAP master-data change."),
                            html.Div([html.Strong("Allowed: "), "Draft package for human review."], style={"color": COLORS["green"], "fontWeight": 800}),
                            html.Div([html.Strong("Blocked: "), "Direct SAP update or unattended PM reduction."], style={"color": COLORS["red"], "fontWeight": 800, "marginTop": "6px"}),
                        ],
                        className="recommendation-card",
                    ),
                    html.Div(
                        [
                            html.Div([html.Span("DRAFT", className="draft-badge"), html.Span("  PKG-PUMP-4110-STRAT-001", style={"fontWeight": 900})]),
                            html.P("Draft scope: retain current PM coverage, add CBM evidence tasks, and request governed review for any future interval change.", style={"marginTop": "12px"}),
                            html.Div("SAP actions tied to this recommendation", className="artifact-title"),
                            html.Ul([html.Li(a) for a in sap_actions], className="sap-action-list"),
                            html.Div(
                                [
                                    html.Button("Open Draft Package", id="studio-open-draft", className="primary-btn"),
                                    html.Button("Ask MAX why", id="studio-open-ask", className="outline-btn"),
                                ],
                                className="action-row",
                            ),
                        ],
                        className="draft-card",
                    ),
                    artifact_card("Recommendation Evidence", evidence_table()),
                ],
                className="pane panel-pad studio-scroll",
            ),
            html.Div(
                [
                    html.H2("Governance Details", className="panel-title"),
                    html.P("Detailed package and approval rails are tucked here to reduce visual load.", className="muted"),
                    html.Details(
                        [
                            html.Summary("SAP Package Details"),
                            html.Div(
                                [
                                    html.Pre(
                                        "Package ID: PKG-PUMP-4110-STRAT-001\nStatus: DRAFT\nChange Type: PM strategy review\nProposed: add CBM evidence tasks, retain coverage\nSAP write-back: disabled in Wave 1",
                                        className="code-box",
                                    )
                                ]
                            ),
                        ],
                        className="collapse-card",
                    ),
                    html.Details(
                        [
                            html.Summary("Approval Workflow"),
                            html.Div(
                                [
                                    html.P("Required approvers: Planner, Reliability Engineer."),
                                    html.P("Current state: DRAFT."),
                                    html.P("Next transition: ANALYST_REVIEWED after evidence review."),
                                ]
                            ),
                        ],
                        className="collapse-card",
                    ),
                    html.Details(
                        [
                            html.Summary("Tool Trace"),
                            html.Div([gate_table()]),
                        ],
                        className="collapse-card",
                    ),
                ],
                className="pane panel-pad studio-scroll",
            ),
        ],
        className="studio-grid studio-body",
    )

    option_b = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("MAX Recommendation", className="preview-kicker"),
                            html.Div("Draft a governed review package; do not reduce or retire the PM yet.", className="hero-title"),
                            html.P("This option makes the recommendation the first thing the user sees, then lets them scan why and what draft/SAP actions follow."),
                        ]
                    ),
                    html.Div(
                        [
                            html.Div([html.Div("Gate", className="metric-label"), html.Div("REVIEW_REQUIRED", className="metric-value")], className="metric-tile"),
                            html.Div([html.Div("Draft", className="metric-label"), html.Div("PKG-PUMP-4110-STRAT-001", className="metric-value")], className="metric-tile"),
                            html.Div([html.Div("SAP write-back", className="metric-label"), html.Div("BLOCKED", className="metric-value")], className="metric-tile"),
                        ],
                        className="summary-strip",
                    ),
                ],
                className="hero-recommendation",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("Why MAX Recommended This", className="panel-title"),
                            *[html.Div([html.Div(label, className="artifact-title"), html.P(body, className="muted")], className="artifact-card") for label, body in why_items],
                        ],
                        className="pane panel-pad studio-scroll",
                    ),
                    html.Div(
                        [
                            html.H2("Draft and SAP Actions", className="panel-title"),
                            html.Div(
                                [
                                    html.Div([html.Span("DRAFT", className="draft-badge"), html.Span("  PKG-PUMP-4110-STRAT-001", style={"fontWeight": 900})]),
                                    html.P("Draft scope: retain PM coverage, add CBM evidence tasks, and request governed review before strategy changes."),
                                    html.Div("SAP actions tied to this recommendation", className="artifact-title"),
                                    html.Ul([html.Li(a) for a in sap_actions], className="sap-action-list"),
                                ],
                                className="draft-card",
                            ),
                            html.Details([html.Summary("SAP Package Details"), html.Div([html.Pre("Package ID: PKG-PUMP-4110-STRAT-001\nStatus: DRAFT\nSAP write-back: disabled in Wave 1", className="code-box")])], className="collapse-card"),
                            html.Details([html.Summary("Approval Workflow"), html.Div([html.P("Required approvers: Planner, Reliability Engineer."), html.P("Current state: DRAFT.")])], className="collapse-card"),
                        ],
                        className="pane panel-pad studio-scroll",
                    ),
                ],
                className="studio-b-lower",
            ),
        ],
        className="studio-grid-b studio-body",
    )

    option_c = html.Div(
        [
            html.Div(
                [
                    html.H2("DRAFT Package Workbench", className="panel-title"),
                    html.Div(
                        [
                            html.Div([html.Span("DRAFT", className="draft-badge"), html.Span("  PKG-PUMP-4110-STRAT-001", style={"fontWeight": 900})]),
                            html.Div([html.Div("Recommendation", className="field-label"), html.Div("Retain current PM coverage. Add CBM evidence tasks. Route for governed review before strategy change.", className="field-value")], className="draft-field"),
                            html.Div([html.Div("SAP actions tied to recommendation", className="field-label"), html.Ul([html.Li(a) for a in sap_actions], className="sap-action-list")], className="draft-field"),
                            html.Div([html.Div("Blocked action", className="field-label"), html.Div("Direct SAP update or unattended PM reduction.", className="field-value", style={"color": COLORS["red"]})], className="draft-field"),
                        ],
                        className="draft-editor",
                    ),
                    html.Div([html.Button("Ask MAX why", id="studio-open-ask", className="outline-btn")], className="action-row"),
                ],
                className="pane panel-pad studio-scroll",
            ),
            html.Div(
                [
                    html.H2("Why MAX Recommended This", className="panel-title"),
                    html.Div(
                        [
                            html.Div([html.Div(str(i + 1), className="step-num"), html.Div([html.Div(label, className="artifact-title"), html.P(body, className="muted")])], className="step-item")
                            for i, (label, body) in enumerate(why_items)
                        ],
                        className="step-list",
                    ),
                    artifact_card("Recommendation Evidence", evidence_table()),
                ],
                className="pane panel-pad studio-scroll",
            ),
            html.Div(
                [
                    html.H2("Governance Details", className="panel-title"),
                    html.P("This option keeps governance tucked away unless the reviewer needs it.", className="muted"),
                    html.Details([html.Summary("SAP Package Details"), html.Div([html.Pre("Package ID: PKG-PUMP-4110-STRAT-001\nStatus: DRAFT\nChange Type: PM strategy review", className="code-box")])], className="collapse-card"),
                    html.Details([html.Summary("Approval Workflow"), html.Div([html.P("Planner and Reliability Engineer required."), html.P("Next state: ANALYST_REVIEWED.")])], className="collapse-card"),
                    html.Details([html.Summary("Tool Trace"), html.Div([gate_table()])], className="collapse-card"),
                ],
                className="pane panel-pad studio-scroll",
            ),
        ],
        className="studio-grid-c studio-body",
    )

    body = option_b if state.studio_variant == "b" else option_c if state.studio_variant == "c" else option_a
    return html.Div(
        [header, body],
        className="studio-page",
    )


def layout_from_state(state: AskState) -> html.Div:
    if state.workspace == "command":
        body = command_center_workspace(state)
    elif state.workspace == "studio":
        body = html.Div(studio_workspace(state), className="studio-wrap")
    else:
        body = ask_workspace(state)
    return html.Div([context_row(state), body])


app = Dash(__name__, title="MAX Ask Prototype", suppress_callback_exceptions=True)
app.index_string = (
    "<!DOCTYPE html><html><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}"
    "<style>"
    + css_text()
    + "</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"
)
app.layout = html.Div(
    [
        dcc.Store(id="ui-state", data=AskState().as_dict()),
        top_bar(AskState()),
        html.Div(id="prototype-root"),
    ],
    className="app-shell",
)


@app.callback(
    Output("prototype-root", "children"),
    Output("nav-command", "className"),
    Output("nav-ask", "className"),
    Output("nav-studio", "className"),
    Input("ui-state", "data"),
)
def render(data: dict[str, Any] | None):
    state = AskState.from_dict(data)

    def nav_class(workspace: str) -> str:
        return "workspace-tab active" if state.workspace == workspace else "workspace-tab"

    return layout_from_state(state), nav_class("command"), nav_class("ask"), nav_class("studio")


@app.callback(
    Output("ui-state", "data", allow_duplicate=True),
    Input("nav-command", "n_clicks"),
    Input("nav-ask", "n_clicks"),
    Input("nav-studio", "n_clicks"),
    State("ui-state", "data"),
    prevent_initial_call=True,
)
def navigate(_command: int | None, _ask: int | None, _studio: int | None, data: dict[str, Any] | None):
    state = AskState.from_dict(data)
    triggered = current_triggered_id()
    if triggered == "nav-command":
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=None, queue_filter=state.queue_filter, preview_asset=None, studio_variant=state.studio_variant).as_dict()
    if triggered == "nav-ask":
        return AskState(workspace="ask", panel=state.panel, query=state.query, resolved_asset=state.resolved_asset, queue_filter=state.queue_filter, preview_asset=state.preview_asset, studio_variant=state.studio_variant).as_dict()
    if triggered == "nav-studio":
        asset = state.preview_asset or state.resolved_asset or "PUMP-4110"
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset, studio_variant=state.studio_variant).as_dict()
    return state.as_dict()


@app.callback(
    Output("ui-state", "data", allow_duplicate=True),
    Input("studio-option-a", "n_clicks", allow_optional=True),
    Input("studio-option-b", "n_clicks", allow_optional=True),
    Input("studio-option-c", "n_clicks", allow_optional=True),
    State("ui-state", "data"),
    prevent_initial_call=True,
)
def studio_option(_a: int | None, _b: int | None, _c: int | None, data: dict[str, Any] | None):
    state = AskState.from_dict(data)
    triggered = current_triggered_id()
    variant = {"studio-option-a": "a", "studio-option-b": "b", "studio-option-c": "c"}.get(triggered, state.studio_variant)
    asset = state.resolved_asset or state.preview_asset or "PUMP-4110"
    return AskState(
        workspace="studio",
        panel=state.panel,
        query=f"Review PM strategy for {asset}",
        resolved_asset=asset,
        queue_filter=state.queue_filter,
        preview_asset=asset,
        studio_variant=variant,
    ).as_dict()


@app.callback(
    Output("ui-state", "data", allow_duplicate=True),
    Input("priority-all", "n_clicks", allow_optional=True),
    *[Input(f"priority-{value}", "n_clicks", allow_optional=True) for value, _label, _count, _note in PRIORITY_TILES],
    *[Input(f"pm-preview-{row['asset']}", "n_clicks", allow_optional=True) for row in QUEUE_ROWS],
    *[Input(f"pm-studio-{row['asset']}", "n_clicks", allow_optional=True) for row in QUEUE_ROWS],
    Input("command-preview-ask", "n_clicks", allow_optional=True),
    Input("command-preview-studio", "n_clicks", allow_optional=True),
    State("ui-state", "data"),
    prevent_initial_call=True,
)
def command_actions(*values):
    state = AskState.from_dict(values[-1])
    triggered = current_triggered_id()
    if isinstance(triggered, str) and triggered.startswith("priority-"):
        value = triggered.replace("priority-", "", 1)
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=None, queue_filter=value or "all", preview_asset=None).as_dict()
    if isinstance(triggered, str) and triggered.startswith("pm-preview-"):
        asset = triggered.replace("pm-preview-", "", 1)
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if isinstance(triggered, str) and triggered.startswith("pm-studio-"):
        asset = triggered.replace("pm-studio-", "", 1)
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if triggered == "command-preview-ask":
        asset = state.preview_asset or state.resolved_asset or "PUMP-4110"
        return AskState(workspace="ask", panel="artifacts", query=f"Should we change PM strategy for {asset}?", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if triggered == "command-preview-studio":
        asset = state.preview_asset or state.resolved_asset or "PUMP-4110"
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    return state.as_dict()


@app.callback(
    Output("ui-state", "data", allow_duplicate=True),
    Input("ask-send", "n_clicks", allow_optional=True),
    Input("ask-input", "n_submit", allow_optional=True),
    Input("action-dashboard", "n_clicks", allow_optional=True),
    Input("action-preview", "n_clicks", allow_optional=True),
    Input("action-studio", "n_clicks", allow_optional=True),
    Input("preview-open-studio", "n_clicks", allow_optional=True),
    Input("panel-artifacts", "n_clicks", allow_optional=True),
    Input("panel-dashboard", "n_clicks", allow_optional=True),
    Input("panel-preview", "n_clicks", allow_optional=True),
    Input("back-ask", "n_clicks", allow_optional=True),
    Input("studio-open-ask", "n_clicks", allow_optional=True),
    Input("studio-open-draft", "n_clicks", allow_optional=True),
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
    triggered = current_triggered_id()
    ask_value = values[-2]
    state = AskState.from_dict(values[-1])
    if not triggered:
        return no_update

    if triggered in ("ask-send", "ask-input"):
        query = (ask_value or "").strip() or state.query
        return AskState(workspace="ask", panel="artifacts", query=query, resolved_asset=resolve_asset(query), queue_filter=state.queue_filter).as_dict()

    if isinstance(triggered, dict) and triggered.get("type") == "followup":
        label = triggered.get("label", "")
        query = label
        if label == "Pick a PM to preview":
            query = "Show preview for PUMP-4110"
        return AskState(workspace="ask", panel="artifacts", query=query, resolved_asset=resolve_asset(query) or state.resolved_asset, queue_filter=state.queue_filter).as_dict()

    if isinstance(triggered, dict) and triggered.get("type") == "priority-filter":
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=None, queue_filter=triggered.get("value") or "all", preview_asset=None).as_dict()

    if isinstance(triggered, dict) and triggered.get("type") == "pm-preview":
        asset = triggered.get("asset")
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()

    if isinstance(triggered, dict) and triggered.get("type") == "pm-studio":
        asset = triggered.get("asset")
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()

    if isinstance(triggered, str) and triggered.startswith("priority-"):
        value = triggered.replace("priority-", "", 1)
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=None, queue_filter=value or "all", preview_asset=None).as_dict()

    if isinstance(triggered, str) and triggered.startswith("pm-preview-"):
        asset = triggered.replace("pm-preview-", "", 1)
        return AskState(workspace="command", panel=state.panel, query=state.query, resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()

    if isinstance(triggered, str) and triggered.startswith("pm-studio-"):
        asset = triggered.replace("pm-studio-", "", 1)
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()

    if triggered == "action-dashboard" or triggered == "panel-dashboard":
        return AskState(workspace="ask", panel="dashboard", query=state.query, resolved_asset=state.resolved_asset, queue_filter=state.queue_filter, preview_asset=state.preview_asset).as_dict()
    if triggered == "action-preview" or triggered == "panel-preview":
        panel = "preview" if state.has_preview else "artifacts"
        return AskState(workspace="ask", panel=panel, query=state.query, resolved_asset=state.resolved_asset, queue_filter=state.queue_filter, preview_asset=state.preview_asset).as_dict()
    if triggered == "panel-artifacts":
        return AskState(workspace="ask", panel="artifacts", query=state.query, resolved_asset=state.resolved_asset, queue_filter=state.queue_filter, preview_asset=state.preview_asset).as_dict()
    if triggered in ("action-studio", "preview-open-studio", "command-preview-studio"):
        asset = state.preview_asset or state.resolved_asset or "PUMP-4110"
        return AskState(workspace="studio", panel=state.panel, query=f"Review PM strategy for {asset}", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if triggered in ("nav-ask", "back-ask"):
        return AskState(workspace="ask", panel=state.panel, query=state.query, resolved_asset=state.resolved_asset, queue_filter=state.queue_filter, preview_asset=state.preview_asset).as_dict()
    if triggered == "command-preview-ask":
        asset = state.preview_asset or state.resolved_asset or "PUMP-4110"
        return AskState(workspace="ask", panel="artifacts", query=f"Should we change PM strategy for {asset}?", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if triggered == "studio-open-ask":
        asset = state.resolved_asset or state.preview_asset or "PUMP-4110"
        return AskState(workspace="ask", panel="artifacts", query=f"Why did MAX recommend the draft package for {asset}?", resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()
    if triggered == "studio-open-draft":
        asset = state.resolved_asset or state.preview_asset or "PUMP-4110"
        return AskState(workspace="studio", panel=state.panel, query=state.query, resolved_asset=asset, queue_filter=state.queue_filter, preview_asset=asset).as_dict()

    return state.as_dict()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8061"))
    app.run(host="127.0.0.1", port=port, debug=False)
