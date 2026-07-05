"""MAX Agent - Databricks App entry point (Dash).

Runs locally on synthetic data with no Databricks connection, and on Databricks Apps once a workspace
/ SQL warehouse / Genie space / LLM serving endpoint are bound. Deterministic tools DECIDE; MAX (the
LLM) selects/sequences tools and narrates; MAX never writes SAP in Wave 1.

Left panel is ChatGPT-style: transcript on top, input pinned at the bottom, empty until you ask. When
you Ask, MAX shows a live 'MAX is thinking / running <tool> / synthesizing' status while it works.
"""

from __future__ import annotations

import os
import threading

from dash import Dash, Input, Output, State, ctx, html, no_update
from flask import request

from max_agent.orchestrator import MaxAgent
from max_agent.intent import resolve_asset_from_text
from max_agent.ui.artifacts import (
    render_comparison,
    render_context_bar,
    render_decision,
    render_evidence,
    render_sap_package,
    render_tool_trace,
)
from max_agent.ui.chat import render_chat, render_process, render_user_bubble
from max_agent.ui.command_center import (
    PRIORITY_KEYS,
    _PRIORITY,
    priority_match,
    priority_tile_style,
    render_pm_preview,
)
from max_agent.ui.layout import build_layout, nav_button_style
from max_agent.ui.theme import MUTED

agent = MaxAgent()
# PM Health is deterministic/static for the synthetic fleet; compute once (queue-first landing).
PORTFOLIO_HEALTH = agent.portfolio_health()

app = Dash(__name__, title="MAX Agent", suppress_callback_exceptions=True)
server = app.server  # WSGI entry point for gunicorn / Databricks Apps
app.layout = build_layout(agent, PORTFOLIO_HEALTH)


# --- live-progress store (per browser session) ---------------------------------
_PROG: dict = {}
_PROG_LOCK = threading.Lock()


def _prog_start(sid: str) -> None:
    with _PROG_LOCK:
        _PROG[sid] = {"steps": ["thinking"], "status": "running"}


def _prog_step(sid: str, tool: str) -> None:
    with _PROG_LOCK:
        p = _PROG.setdefault(sid, {"steps": ["thinking"], "status": "running"})
        p["status"] = "running"
        if tool == "thinking":
            return  # keep the current head (initial 'thinking' or the last tool)
        if p["steps"] == ["thinking"]:
            p["steps"] = []  # first real step replaces the initial 'thinking'
        if not p["steps"] or p["steps"][-1] != tool:
            p["steps"].append(tool)


def _prog_done(sid: str) -> None:
    with _PROG_LOCK:
        if sid in _PROG:
            _PROG[sid]["status"] = "done"


def _prog_get(sid: str) -> dict:
    with _PROG_LOCK:
        p = _PROG.get(sid, {"steps": [], "status": "idle"})
        return {"steps": list(p.get("steps", [])), "status": p.get("status", "idle")}


def _current_actor() -> dict:
    """Resolve the acting user from Databricks Apps auth headers; a typed name is never authorization."""
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


# A per-browser session id (so one user's live status never leaks into another's).
app.clientside_callback(
    "function(_){ return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('s'+Math.random().toString(36).slice(2)); }",
    Output("session-id", "data"),
    Input("session-id", "id"),
)


# --- workspace shell: Command Center / Ask MAX / Work Strategy Studio ---------
@app.callback(
    Output("workspace", "data"),
    Input("nav-command", "n_clicks"),
    Input("nav-ask", "n_clicks"),
    Input("nav-studio", "n_clicks"),
    prevent_initial_call=True,
)
def set_workspace(_c, _a, _s):
    trig = ctx.triggered_id
    if trig in ("nav-command", "nav-ask", "nav-studio"):
        return trig.split("-", 1)[1]
    return no_update


@app.callback(
    Output("ws-command", "style"),
    Output("ws-ask", "style"),
    Output("ws-studio", "style"),
    Output("nav-command", "style"),
    Output("nav-ask", "style"),
    Output("nav-studio", "style"),
    Input("workspace", "data"),
)
def render_workspace(workspace):
    workspace = workspace or "command"
    hide = {"display": "none"}
    return (
        {"display": "block"} if workspace == "command" else hide,
        {"display": "block"} if workspace == "ask" else hide,
        {"display": "block", "padding": "18px 22px"} if workspace == "studio" else {"display": "none", "padding": "18px 22px"},
        nav_button_style(workspace == "command"),
        nav_button_style(workspace == "ask"),
        nav_button_style(workspace == "studio"),
    )


@app.callback(
    Output("chat-status", "children"),
    Input("thinking-interval", "n_intervals"),
    State("session-id", "data"),
)
def poll_status(_n, session_id):
    """Live 'MAX is ...' indicator; polled while MAX runs (in parallel with the main callback)."""
    p = _prog_get(session_id or "ui")
    if p.get("status") != "running":
        return ""
    return render_process(p.get("steps") or ["thinking"])


@app.callback(
    Output("context-bar", "children"),
    Output("chat-output", "children"),
    Output("tab-decision", "children"),
    Output("tab-evidence", "children"),
    Output("tab-comparison", "children"),
    Output("tab-sap", "children"),
    Output("tab-trace", "children"),
    Input("asset-dropdown", "value"),
    Input("time-window", "value"),
    Input("review-type", "value"),
    Input("approval-audit", "data"),
    Input("chat-question", "data"),
    State("session-id", "data"),
)
def on_context(equipment_id, time_window, review_type, audit, chat_question, session_id):
    actor = _current_actor()
    sid = session_id or "ui"
    # Narrate (run MAX) only when the ASK triggered this render; browsing stays fast and shows no answer.
    triggered = {t["prop_id"].split(".")[0] for t in (ctx.triggered or [])}
    question = None
    if "chat-question" in triggered and chat_question:
        r = resolve_asset_from_text(chat_question, agent._fleet_index)
        reid = r.get("equipment_id")
        if reid is None or reid == equipment_id:
            question = chat_question

    on_step = None
    if question:
        _prog_start(sid)

        def on_step(tool, _sid=sid):  # noqa: E306  (appends each step to the live checklist)
            _prog_step(_sid, tool)

    result = agent.run(equipment_id, actor=actor, time_window=time_window, review_type=review_type,
                       question=question, thread_id=sid, on_step=on_step)
    if question:
        _prog_done(sid)

    if result.get("error"):
        blank = html.Div("-", style=MUTED)
        return (html.Div(), html.Div(result["error"], style={"color": "#b42318"}),
                blank, blank, blank, blank, blank)

    chat = render_chat(result) if question else html.Div()  # empty until you ask
    return (
        render_context_bar(result),
        chat,
        render_decision(result),
        render_evidence(result),
        render_comparison(result),
        render_sap_package(result, audit=audit),
        render_tool_trace(result),
    )


@app.callback(
    Output("chat-echo", "children"),
    Output("asset-dropdown", "value", allow_duplicate=True),
    Output("chat-question", "data"),
    Input("chat-send", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    State("asset-dropdown", "value"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def on_chat(_clicks, _submit, text, current_asset, session_id):
    text = (text or "").strip()
    if not text:
        return no_update, no_update, no_update
    # Show the "MAX is thinking" indicator immediately (before the ~20s run starts).
    _prog_start(session_id or "ui")
    resolved = resolve_asset_from_text(text, agent._fleet_index)
    eid = resolved.get("equipment_id")
    bubble = render_user_bubble(text)
    if eid:
        return bubble, eid, text
    return bubble, no_update, text  # names no asset -> answer for the currently-selected one


# --- Command Center interactions ----------------------------------------------
@app.callback(
    Output("cc-preview", "children"),
    Output("asset-dropdown", "value", allow_duplicate=True),
    Output("workspace", "data", allow_duplicate=True),
    Input("pmhealth-table", "active_cell"),
    State("pmhealth-table", "data"),
    prevent_initial_call=True,
)
def on_queue_click(active_cell, data):
    if not active_cell or not data:
        return no_update, no_update, no_update
    row = active_cell.get("row")
    if row is None or row >= len(data):
        return no_update, no_update, no_update
    eid = data[row].get("equipment_id")
    if active_cell.get("column_id") in ("equipment_id", "pm_id"):
        return no_update, eid, "studio"  # asset / PM name -> Work Strategy Studio directly
    return render_pm_preview(agent.run(eid)), eid, no_update  # row body -> PM preview slide-over


@app.callback(
    Output("workspace", "data", allow_duplicate=True),
    Output("cc-preview", "children", allow_duplicate=True),
    Input("cc-ask-btn", "n_clicks"),
    Input("cc-studio-btn", "n_clicks"),
    Input("cc-preview-close", "n_clicks"),
    prevent_initial_call=True,
)
def on_preview_action(ask, studio, close):
    trig = ctx.triggered_id
    # Guard on n_clicks so the dynamically-created buttons don't fire on creation (n_clicks=0).
    if trig == "cc-ask-btn" and ask:
        return "ask", no_update       # both carry the already-set asset scope forward
    if trig == "cc-studio-btn" and studio:
        return "studio", no_update
    if trig == "cc-preview-close" and close:
        return no_update, html.Div()  # clear the slide-over
    return no_update, no_update


@app.callback(
    Output("pmhealth-table", "data"),
    Output("cc-active-priority", "data"),
    Output("cc-prio-blocked", "style"),
    Output("cc-prio-review", "style"),
    Output("cc-prio-draft", "style"),
    Output("cc-prio-missing", "style"),
    Output("cc-prio-readiness", "style"),
    Input("cc-prio-blocked", "n_clicks"),
    Input("cc-prio-review", "n_clicks"),
    Input("cc-prio-draft", "n_clicks"),
    Input("cc-prio-missing", "n_clicks"),
    Input("cc-prio-readiness", "n_clicks"),
    State("cc-active-priority", "data"),
    State("cc-all-rows", "data"),
    prevent_initial_call=True,
)
def on_priority(*args):
    all_rows, active = args[-1], args[-2]
    key = (ctx.triggered_id or "").replace("cc-prio-", "")
    new_active = None if active == key else key  # clicking the active tile clears the filter
    data = all_rows if new_active is None else [d for d in (all_rows or []) if priority_match(d, key)]
    styles = tuple(priority_tile_style(k == new_active, _PRIORITY[k][2]) for k in PRIORITY_KEYS)
    return (data, new_active) + styles


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
    mapping = {
        "approve-btn": ("APPROVE", "ANALYST_REVIEWED"),
        "request-btn": ("REQUEST_CHANGES", "REQUEST_CHANGES"),
        "reject-btn": ("REJECT", "REJECTED"),
    }
    trig = mapping.get(ctx.triggered_id)
    if not trig:
        return no_update
    action, transition = trig
    actor = _current_actor()

    # A click is NOT authorization. Route it through the deterministic approval tool.
    from max_agent.tools import approval_workflow_state
    asset = agent._fleet_index.get(equipment_id, {})
    r = agent.run(equipment_id)
    wf = approval_workflow_state(
        package_id=f"PKG-{equipment_id}", current_state="DRAFT", requested_transition=transition,
        actor=actor, gate_status=r.get("gate_status"),
        readiness=asset.get("readiness", {}), approval_state=asset.get("approval_state", {}),
        creator_user_id="analyst-09",
    ).get("data", {})
    authorized = bool(wf.get("transition_allowed"))

    from datetime import datetime, timezone
    entry = {
        "equipment_id": equipment_id, "action": action, "actor": actor.get("user_id"),
        "comment": (comment or "").strip(),
        "outcome": "AUTHORIZED" if authorized else "DENIED",
        "reason": None if authorized else (wf.get("blocked_transition_reason") or "role not verified"),
        "role_verified": bool(wf.get("role_verified")),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return (audit or []) + [entry]


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
