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
    # Governed lane: the reliability / drift / cost evidence block (tools 25-30)
    "reliability_evidence": "reading reliability & drift evidence",
    # Free-flow lane: a per-turn group header + the read-only tools the model may select. Keys match the
    # tool names emitted by run_free_flow_agent so each selected tool renders as its own checklist row.
    "planning": "deciding what to read",
    "governed_decision": "reading the frozen decision",
    "evidence": "pulling scoped evidence",
    "like_equipment_comparison": "comparing like equipment",
    "reliability": "reading reliability evidence",
    "reliability_drift": "reading drift / anomaly signals",
    "cost_distribution": "reading the cost distribution",
    "parts_bom": "checking parts / BOM completeness",
    "preview_gate_check": "previewing the gate (advisory)",
}


def render_user_bubble(text: str) -> html.Div:
    return html.Div(text or "", className="max-user-bubble")


def render_thinking(step: str) -> html.Div:
    """A single live indicator: a pulsing dot + 'MAX is <friendly step>...'."""
    phrase = STEP_LABELS.get(step, step or "thinking")
    return html.Div([
        html.Span(className="max-thinking-dot"),
        html.Span(f"MAX is {phrase}...", className="max-thinking"),
    ], style={"display": "flex", "alignItems": "center", "padding": "6px 2px"})


def render_process(steps) -> html.Div:
    """The live checklist: completed steps get a green dot, the current step pulses.

    steps is an ordered list of step keys (tool names + 'thinking'/'synthesizing'); the last entry is
    the one MAX is on now.
    """
    steps = steps or []
    if not steps:
        return html.Div()
    rows = []
    last = len(steps) - 1
    row_style = {"display": "flex", "alignItems": "center", "padding": "3px 0"}
    for i, s in enumerate(steps):
        phrase = STEP_LABELS.get(s, s)
        if i == last:  # current step - pulsing
            rows.append(html.Div([html.Span(className="max-thinking-dot"),
                                  html.Span(f"MAX is {phrase}...", className="max-thinking")], style=row_style))
        else:          # completed step - static green dot
            rows.append(html.Div([html.Span(className="max-done-dot"),
                                  html.Span(phrase, className="max-done")], style=row_style))
    return html.Div(rows, style={"padding": "6px 2px"})


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


def render_answer_bubble(summary: str) -> html.Div:
    """One MAX answer bubble from a stored summary string (used by the accumulating transcript)."""
    summary = summary or ""
    if not summary:
        return html.Div()
    return html.Div([
        html.Div("MAX", style={"fontSize": "11px", "fontWeight": 700, "color": COLORS["oxy"], "marginBottom": "4px"}),
        dcc.Markdown(summary, style={"fontSize": "13px", "lineHeight": "1.5", "color": COLORS["ink"]}),
    ], className="max-answer-bubble")


def render_inline_approval(equipment_id: str, key: int, gate_status: str = None, approve_ok: bool = True) -> html.Div:
    """Inline approve / request-changes / reject buttons MAX surfaces in the chat for the last governed
    recommendation. A click is NOT authorization: app.on_inline_approval routes it through the deterministic
    approval_workflow_state tool (role + gate + self-approval + audit). Approve is disabled only when the
    package cannot enter the approval path (BLOCKED / DRAFT_ONLY); REVIEW_REQUIRED can be reviewed, so its
    click reaches the tool which makes the authoritative call. Draft-only; MAX never writes SAP.

    The button ids are pattern-matched on `key` (the message's transcript index) so multiple approval
    prompts never collide."""
    btn = {"border": "none", "borderRadius": "8px", "padding": "7px 12px", "marginRight": "8px",
           "fontWeight": 700, "fontSize": "12px", "cursor": "pointer", "color": "white"}
    note = ("Your click is checked against your role and the gate, recorded to the audit trail, and never "
            "writes SAP.")
    if not approve_ok:
        note += f" (Approve is disabled - gate {gate_status} cannot enter the approval path.)"
    return html.Div([
        html.Div(f"Approve MAX's governed recommendation for {equipment_id}?",
                 style={"fontSize": "13px", "fontWeight": 700, "color": COLORS["ink"], "marginBottom": "6px"}),
        html.Div([
            html.Button("Approve", id={"type": "ff-approve", "key": key}, n_clicks=0, disabled=not approve_ok,
                        style={**btn, "background": "#1a7f37" if approve_ok else "#9aa5ad",
                               "cursor": "pointer" if approve_ok else "not-allowed"}),
            html.Button("Request changes", id={"type": "ff-request", "key": key}, n_clicks=0,
                        style={**btn, "background": "#b7791f"}),
            html.Button("Reject", id={"type": "ff-reject", "key": key}, n_clicks=0,
                        style={**btn, "background": "#b42318"}),
        ]),
        html.Div(note, style={"fontSize": "11px", "color": COLORS["muted"], "marginTop": "6px"}),
    ], className="max-answer-bubble")


def render_transcript(messages) -> html.Div:
    """Render the full accumulated Ask MAX conversation, oldest at top -> newest at bottom.

    Each stored turn is {"role": "user", "content": ...}, {"role": "assistant", "summary": ...}, or an
    APPROVAL prompt {"role": "assistant", "kind": "approval", "equipment_id": ..., ...} which renders inline
    approve/reject buttons. Re-rendered from the message store on every turn (the Finance-agent pattern),
    so past questions and answers stay visible instead of being overwritten.
    """
    bubbles = []
    for idx, m in enumerate(messages or []):
        role = m.get("role")
        if role == "user":
            bubbles.append(render_user_bubble(m.get("content", "")))
        elif role == "assistant" and m.get("kind") == "approval":
            bubbles.append(render_inline_approval(m.get("equipment_id"), idx,
                                                  gate_status=m.get("gate_status"),
                                                  approve_ok=m.get("approve_ok", True)))
        elif role == "assistant":
            bubbles.append(render_answer_bubble(m.get("summary", "")))
    return html.Div(bubbles, style={"display": "flex", "flexDirection": "column", "gap": "10px"})
