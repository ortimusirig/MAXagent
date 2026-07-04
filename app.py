"""MAX Agent - Databricks App entry point (Dash).

Runs locally on synthetic data with no Databricks connection, and on Databricks Apps once a
workspace / SQL warehouse / Genie space / LLM serving endpoint are bound (see app.yaml, DEPLOY.md).
Deterministic tools decide; the LLM only narrates; MAX never writes SAP in Wave 1.

Interaction model (60/04, 30/AppExp): top context bar (filters drive scope), left conversation
(free-text chat OR asset pick), right artifact tabs; PM Health is the queue-first landing tab and a
row click locks that asset's context across every tab.
"""

from __future__ import annotations

import os

from dash import Dash, Input, Output, State, ctx, html, no_update
from flask import request

from max_agent.orchestrator import MaxAgent
from max_agent.intent import resolve_asset_from_text
from max_agent.ui.artifacts import (
    render_comparison,
    render_context_bar,
    render_decision,
    render_evidence,
    render_pills,
    render_pm_health,
    render_sap_package,
    render_tool_trace,
)
from max_agent.ui.chat import render_chat
from max_agent.ui.layout import build_layout
from max_agent.ui.theme import COLORS, MUTED

agent = MaxAgent()
# PM Health is deterministic/static for the synthetic fleet; compute once (queue-first landing).
PORTFOLIO_HEALTH = agent.portfolio_health()

app = Dash(__name__, title="MAX Agent", suppress_callback_exceptions=True)
server = app.server  # WSGI entry point for gunicorn / Databricks Apps
app.layout = build_layout(agent)


def _current_actor() -> dict:
    """Resolve the acting user from Databricks Apps auth headers; a typed name is never authorization.

    Databricks Apps inject the signed-in principal via X-Forwarded-* headers. Locally these are
    absent and we fall back to a clearly non-authoritative local actor.
    """
    try:
        h = request.headers
        email = h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username") or h.get("X-Forwarded-User")
        groups = h.get("X-Forwarded-Groups") or ""
        if email:
            roles = [g.strip() for g in groups.split(",") if g.strip()]
            return {"user_id": email, "roles": roles, "source": "databricks_sign_in"}
    except Exception:
        pass
    return {"user_id": "local", "roles": [], "source": "local"}


@app.callback(
    Output("context-bar", "children"),
    Output("user-question", "children"),
    Output("tool-pills", "children"),
    Output("chat-output", "children"),
    Output("tab-pmhealth", "children"),
    Output("tab-decision", "children"),
    Output("tab-evidence", "children"),
    Output("tab-comparison", "children"),
    Output("tab-sap", "children"),
    Output("tab-trace", "children"),
    Input("asset-dropdown", "value"),
    Input("time-window", "value"),
    Input("review-type", "value"),
    Input("approval-audit", "data"),
)
def on_context(equipment_id, time_window, review_type, audit):
    result = agent.run(equipment_id, actor=_current_actor(), time_window=time_window, review_type=review_type)
    if result.get("error"):
        msg = html.Div(result["error"], style={"color": "#b42318"})
        blank = html.Div("-", style=MUTED)
        return html.Div(), "", html.Div(), msg, render_pm_health(PORTFOLIO_HEALTH), blank, blank, blank, blank, blank
    question = '"' + str(result.get("user_question", "")) + '"'
    return (
        render_context_bar(result),
        question,
        render_pills(result),
        render_chat(result),
        render_pm_health(PORTFOLIO_HEALTH),
        render_decision(result),
        render_evidence(result),
        render_comparison(result),
        render_sap_package(result, audit=audit),
        render_tool_trace(result),
    )


@app.callback(
    Output("chat-echo", "children"),
    Output("asset-dropdown", "value", allow_duplicate=True),
    Input("chat-send", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    prevent_initial_call=True,
)
def on_chat(_clicks, _submit, text):
    resolved = resolve_asset_from_text(text or "", agent._fleet_index)
    eid = resolved.get("equipment_id")
    if not eid:
        echo = html.Div([
            html.Div("You asked:", style={**MUTED, "fontSize": "11px"}),
            html.Div(f'"{text or ""}"', style={"fontStyle": "italic", "fontSize": "13px"}),
            html.Div("Could not resolve an in-scope asset from that. Pick an asset above, or name an asset id / class.",
                     style={"color": "#b7791f", "fontSize": "12px", "marginTop": "4px"}),
        ])
        return echo, no_update
    echo = html.Div([
        html.Div("You asked:", style={**MUTED, "fontSize": "11px"}),
        html.Div(f'"{text}"', style={"fontStyle": "italic", "fontSize": "13px"}),
        html.Div(f"Resolved to {eid} (matched on {resolved.get('matched_on')}).",
                 style={"color": COLORS["oxy"], "fontSize": "12px", "marginTop": "4px", "fontWeight": 600}),
    ])
    return echo, eid


@app.callback(
    Output("asset-dropdown", "value", allow_duplicate=True),
    Input("pmhealth-table", "active_cell"),
    State("pmhealth-table", "data"),
    prevent_initial_call=True,
)
def on_drilldown(active_cell, data):
    if not active_cell or not data:
        return no_update
    row = active_cell.get("row")
    if row is None or row >= len(data):
        return no_update
    eid = data[row].get("equipment_id")
    return eid or no_update


@app.callback(
    Output("approval-audit", "data"),
    Input("approve-btn", "n_clicks"),
    Input("request-btn", "n_clicks"),
    Input("reject-btn", "n_clicks"),
    State("approval-comment", "value"),
    State("asset-dropdown", "value"),
    State("approval-audit", "data"),
    prevent_initial_call=True,
)
def on_approval(_a, _r, _j, comment, equipment_id, audit):
    action = {"approve-btn": "APPROVE", "request-btn": "REQUEST_CHANGES", "reject-btn": "REJECT"}.get(ctx.triggered_id)
    if not action:
        return no_update
    actor = _current_actor()
    from datetime import datetime, timezone
    entry = {
        "equipment_id": equipment_id, "action": action, "actor": actor.get("user_id"),
        "comment": (comment or "").strip(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return (audit or []) + [entry]


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
    app.run(host="0.0.0.0", port=port, debug=False)
