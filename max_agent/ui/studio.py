"""Work Strategy Studio: the governed review screen (Option B - recommendation-first).

Studio is where a triaged PM becomes a governed decision. It is the one workspace that OWNS the visible
context / scope bar. The screen leads with MAX's recommendation, explains WHY (grounded in the evidence
MAX already retrieved), then exposes the drafted SAP change package and the governed approve /
request-changes / reject action.

Draft-only in Wave 1: a click is never authorization. The action buttons only REQUEST a transition;
app.on_approval routes it through the deterministic approval_workflow_state tool, which decides
AUTHORIZED / DENIED on role + gate and writes the session audit trail. MAX never writes SAP.
"""

from __future__ import annotations

from typing import Any, Dict, List

from dash import html

from ..labels import change_label, rec_label, rec_meaning
from .artifacts import (
    badge,
    render_context_bar,
    render_governed_action,
    render_sap_package,
    render_why,
)
from .theme import CARD, COLORS, H2, MUTED, STATUS_COLORS


def _empty() -> html.Div:
    return html.Div([
        html.Div("Work Strategy Studio", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"]}),
        html.Div("Open a PM's governed review here by clicking an asset or PM id in the Command Center, "
                 "or by asking MAX about one. Studio leads with MAX's recommendation, the evidence behind "
                 "it, and the draft SAP change package with the governed approve / request-changes / reject "
                 "action - draft-only in Wave 1.",
                 style={**MUTED, "marginTop": "8px", "maxWidth": "72ch"}),
    ], style={"padding": "18px 22px"})


def _hero(result: Dict[str, Any]) -> html.Div:
    rec = result.get("recommendation_type") or "-"
    rec_gate = result.get("recommendation_gate_status")
    rationale = result.get("recommendation_rationale") or "-"
    next_action = result.get("recommendation_next_action") or "-"
    diverges = result.get("recommendation_diverges")
    change = result.get("change_under_review_type")
    kids = [
        html.Div("MAX recommends", style={"fontSize": "12px", "fontWeight": 700, "color": COLORS["muted"],
                                          "textTransform": "uppercase", "letterSpacing": "0.06em"}),
        html.Div([
            html.Span(rec_label(rec), style={"fontSize": "24px", "fontWeight": 800, "color": COLORS["oxy"], "marginRight": "12px"}),
            badge(rec_gate, STATUS_COLORS.get(rec_gate, COLORS["muted"])),
        ], style={"display": "flex", "alignItems": "center", "margin": "6px 0 8px"}),
        # What executing this recommendation means (so the code IMPROVE_TASK_LIST reads as a real action).
        html.Div(rec_meaning(rec), style={**MUTED, "fontStyle": "italic", "marginBottom": "8px"}) if rec_meaning(rec) else html.Div(),
        html.Div(rationale, style={"fontSize": "14px", "color": COLORS["ink"], "lineHeight": "1.55"}),
        html.Div([
            html.Span("Next action: ", style={"fontWeight": 700, "fontSize": "13px", "color": COLORS["ink"]}),
            html.Span(next_action, style={"fontSize": "13px", "color": COLORS["muted"]}),
        ], style={"marginTop": "10px"}),
    ]
    if diverges:
        kids.append(html.Div(
            f"You are reviewing the change '{change_label(change)}', but MAX recommends "
            f"'{rec_label(rec)}' instead. The SAP package below drafts MAX's recommendation and is "
            "gate-checked on its own.",
            style={"background": "#fff4e5", "border": "1px solid #f0c987", "borderRadius": "8px",
                   "padding": "9px", "fontSize": "12px", "color": "#8a5a00", "marginTop": "12px"},
        ))
    return html.Div(kids, style={**CARD, "borderLeft": f"4px solid {COLORS['oxy']}"})


def _why(result: Dict[str, Any], narrative: str) -> html.Div:
    # Shared synthesis block (identical in the Command Center preview) wrapped in the Studio card.
    return html.Div([render_why(result, narrative)], style=CARD)


def _actions(result: Dict[str, Any], audit: List[Dict[str, Any]]) -> html.Div:
    return html.Div([
        html.Div("Draft and SAP actions", style={**H2, "marginTop": "2px"}),
        render_governed_action(result, audit),
        html.Details([
            html.Summary("SAP change package details (draft)",
                         style={"cursor": "pointer", "fontWeight": 700, "fontSize": "13px",
                                "color": COLORS["oxy"], "padding": "8px 0"}),
            render_sap_package(result, with_controls=False),
        ], style={"marginTop": "6px"}),
    ])


def render_studio(result: Dict[str, Any], audit: List[Dict[str, Any]] = None, narrative: str = None) -> html.Div:
    """The full Studio review for one PM: visible context bar, recommendation hero, the evidence-grounded
    'why', and the governed action + collapsible SAP package. Empty state when no PM is selected."""
    if not result or result.get("error"):
        return _empty()
    return html.Div([
        render_context_bar(result),
        html.Div([
            _hero(result),
            _why(result, narrative),
            _actions(result, audit or []),
        ], style={"padding": "16px 22px"}),
    ])
