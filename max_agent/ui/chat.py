"""Chat bubbles for the left panel. MAX-branded (no "LLM" wording): a user question bubble, MAX's
answer bubble (markdown), and a live "MAX is ..." thinking indicator."""

from __future__ import annotations

from typing import Any, Dict

from dash import dcc, html

from .theme import COLORS

# tool name -> friendly progress phrase shown while MAX runs it
STEP_LABELS = {
    "thinking": "thinking",
    "synthesizing": "synthesizing the answer",
    "lock_scope": "checking the asset scope",
    "retrieve_evidence": "retrieving scoped evidence",
    "classify_effectiveness": "classifying PM effectiveness",
    "check_data_readiness": "checking data readiness",
    "recommend_change": "forming a recommendation",
    "run_oxy_gate": "running the Oxy governance gate",
    "execution_readiness": "checking execution readiness",
    "compare_like_equipment": "comparing like equipment",
    "portfolio_health": "reviewing the PM portfolio",
}


def render_user_bubble(text: str) -> html.Div:
    return html.Div(text or "", className="max-user-bubble")


def render_thinking(step: str) -> html.Div:
    """The live indicator: a pulsing dot + 'MAX is <friendly step>...'."""
    phrase = STEP_LABELS.get(step, step or "thinking")
    return html.Div([
        html.Span(className="max-thinking-dot"),
        html.Span(f"MAX is {phrase}...", className="max-thinking"),
    ], style={"display": "flex", "alignItems": "center", "padding": "6px 2px"})


def render_chat(result: Dict[str, Any]) -> html.Div:
    """MAX's answer bubble. Empty until MAX has answered."""
    if not result:
        return html.Div()
    if "error" in result:
        return html.Div(result["error"], className="max-answer-bubble", style={"color": "#b42318"})
    summary = result.get("chat_summary", "") or ""
    if not summary:
        return html.Div()
    return html.Div([
        html.Div("MAX", style={"fontSize": "11px", "fontWeight": 700, "color": COLORS["oxy"], "marginBottom": "4px"}),
        dcc.Markdown(summary, style={"fontSize": "13px", "lineHeight": "1.5", "color": COLORS["ink"]}),
    ], className="max-answer-bubble")
