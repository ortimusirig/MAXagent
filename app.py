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

from dash import ALL, MATCH, Dash, Input, Output, State, ctx, dcc, html, no_update
from flask import request

from max_agent.orchestrator import MaxAgent
from max_agent.intent import resolve_asset_from_text
from max_agent.ui.artifact_catalog import preview_empty, render_artifact_history, render_trace_history
from max_agent.ui.artifacts import _audit_trail, render_context_bar
from max_agent.ui.studio import render_studio
from max_agent.ui.chat import render_chat, render_process, render_transcript, render_user_bubble
from max_agent.ui.command_center import (
    PRIORITY_KEYS,
    _PRIORITY,
    priority_match,
    priority_tile_style,
    render_pm_error,
    render_pm_preview,
)
from max_agent.ui.layout import build_layout, nav_button_style

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


def _last_governed_result(history):
    """The most recent history entry that actually carries a governed `result`.

    Free-flow turns append a card WITHOUT a `result` key (only a `ref` summary), so reading `[-1]` loses
    the grounding after ONE free-flow turn and the next follow-up falls back to GOVERNED (re-runs the
    pipeline). Scanning back keeps the free-flow lane grounded on the last governed decision across
    MULTIPLE consecutive follow-ups - the mental model's "FREE_FLOW uses this turn or the last governed
    result." Read-only: it never mints a new gate/label/recommendation."""
    for entry in reversed(history or []):
        if entry.get("result"):
            return entry.get("result")
    return None


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
        {"display": "block"} if workspace == "studio" else hide,  # Studio content owns its own padding
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
    Output("chat-messages", "data", allow_duplicate=True),
    Output("artifacts-history", "data"),
    Output("artifacts-collapsed", "data"),
    Output("trace-collapsed", "data"),
    Output("tab-dashboard", "children"),
    Output("tab-preview", "children"),
    Input("asset-dropdown", "value"),
    Input("time-window", "value"),
    Input("review-type", "value"),
    Input("chat-question", "data"),
    State("chat-artifacts", "data"),
    State("session-id", "data"),
    State("artifacts-history", "data"),
    State("chat-messages", "data"),
    prevent_initial_call=True,
)
def on_context(equipment_id, time_window, review_type, chat_question, chat_artifacts, session_id, history, messages):
    actor = _current_actor()
    sid = session_id or "ui"
    empty = preview_empty()  # centered icon+text shown in the Preview tab when there is no PM preview
    # Narrate (run MAX) only when the ASK triggered this render; browsing stays fast and shows no answer.
    triggered = {t["prop_id"].split(".")[0] for t in (ctx.triggered or [])}
    question = None
    if "chat-question" in triggered and chat_question:
        r = resolve_asset_from_text(chat_question, agent._fleet_index)
        reid = r.get("equipment_id")
        if reid is None and r.get("candidates"):
            _prog_done(sid)
            choices = ", ".join(r.get("candidates", [])[:8])
            suffix = "..." if len(r.get("candidates", [])) > 8 else ""
            msg = (
                "I found multiple matching assets. Please name the specific equipment ID before I run "
                f"a governed PM review: {choices}{suffix}."
            )
            return (no_update, (messages or []) + [{"role": "assistant", "summary": msg}],
                    no_update, no_update, no_update, no_update, no_update)
        if reid is None or reid == equipment_id:
            question = chat_question

    # FREE-FLOW ROUTING: MAX is free-flow by default; the governance DAG is a route the intent triggers.
    # A follow-up / definition / greeting is answered conversationally from the LAST governed result +
    # glossary + transcript, WITHOUT re-running the pipeline. Read-only: it can never mint a new gate,
    # label, or recommendation. Fail-safe: anything not clearly FREE_FLOW routes to GOVERNED (the DAG).
    if question:
        last_result = _last_governed_result(history)
        if agent.classify_intent(question, messages, has_last_result=bool(last_result)) == "FREE_FLOW":
            _prog_start(sid)

            def on_step(tool, _sid=sid):  # noqa: E306  (display-only: appends each tool to the checklist)
                _prog_step(_sid, tool)

            # Sub-route the free-flow turn: INFO (explain / look up), GATE_CHECK (advisory 'is X allowed'),
            # or APPROVAL (approve / reject the recommendation just discussed).
            ff_intent = agent.classify_free_flow_intent(question, messages, has_last_result=bool(last_result))
            answer = agent.free_flow_answer(question, messages, last_result, intent=ff_intent, on_step=on_step)
            _prog_done(sid)
            msgs = (messages or []) + [{"role": "assistant", "summary": answer}]
            # APPROVAL: MAX SURFACES inline approve/reject buttons for the last governed recommendation.
            # The LLM only proposes the action; the authenticated human clicks (on_inline_approval), and
            # approval_workflow_state checks role + gate + self-approval + audit. Draft-only; never SAP.
            if (ff_intent == "APPROVAL" and last_result and not last_result.get("error")
                    and last_result.get("equipment_id")):
                p = last_result.get("package") or {}
                # Enable Approve when the package can ENTER the human approval path (PASS or REVIEW_REQUIRED),
                # not only when it can SUBMIT (PASS). "Approve" advances DRAFT -> ANALYST_REVIEWED, a review
                # step approval_workflow_state allows for REVIEW_REQUIRED; gating on submit_path_available
                # disabled it for the whole REVIEW_REQUIRED population and pre-empted the deterministic tool.
                approve_ok = bool(p.get("approval_path_available"))
                msgs = msgs + [{"role": "assistant", "kind": "approval",
                                "equipment_id": last_result.get("equipment_id"),
                                "gate_status": last_result.get("gate_status"), "approve_ok": approve_ok}]
            # Free-flow now ALSO produces a READ-ONLY artifact card (summary + detail) in the Artifacts
            # panel, grounded in the last governed decision. No governed pipeline runs, so the context bar
            # and preview stay on the last governed asset (no_update); the entry is marked kind="free_flow"
            # so the history renderers show a free-flow card (and a "no governed pipeline" trace note).
            if last_result and not last_result.get("error"):
                from datetime import datetime
                lr = last_result
                ref = {"equipment_id": lr.get("equipment_id"), "gate_status": lr.get("gate_status"),
                       "gate_reason": lr.get("gate_reason") or lr.get("gate_review_trigger"),
                       "recommendation_type": lr.get("recommendation_type"),
                       "change_under_review_type": lr.get("change_under_review_type"),
                       "evidence_lines": (lr.get("evidence_digest") or {}).get("lines") or []}
                n = max((e.get("n", 0) for e in (history or [])), default=0) + 1
                ff_entry = {"n": n, "question": question, "ts": datetime.now().strftime("%H:%M:%S"),
                            "kind": "free_flow", "intent": ff_intent, "answer": answer, "ref": ref}
                new_history = ((history or []) + [ff_entry])[-15:]
                collapsed = [e.get("n") for e in (history or [])]  # collapse priors; the newest opens
                return (no_update, msgs, new_history, collapsed, collapsed, no_update, no_update)
            # No prior governed result yet (e.g. a greeting before any analysis) -> transcript only.
            return (no_update, msgs, no_update, no_update, no_update, no_update, no_update)

    on_step = None
    if question:
        _prog_start(sid)

        def on_step(tool, _sid=sid):  # noqa: E306  (appends each step to the live checklist)
            _prog_step(_sid, tool)

    result = agent.run(equipment_id, actor=actor, time_window=time_window, review_type=review_type,
                       question=question, thread_id=sid, on_step=on_step)
    if question:
        _prog_done(sid)

    # Browsing / errors never append to the artifacts history (no_update keeps the stack intact).
    if result.get("error"):
        # Only an Ask (question set) surfaces the error as an assistant turn; browsing leaves chat alone.
        err_msgs = ((messages or []) + [{"role": "assistant", "summary": result["error"]}]) if question else no_update
        return (html.Div(), err_msgs, no_update, no_update, no_update, no_update, empty)
    if not question:
        return (html.Div(), no_update, no_update, no_update, no_update, no_update, empty)

    # An answered question APPENDS a new artifact set to the history (newest first, prior ones collapse).
    # The set stores the model-selected artifacts + the governed result so the stack re-renders from state.
    from datetime import datetime
    n = max((e.get("n", 0) for e in (history or [])), default=0) + 1
    entry = {"n": n, "question": question, "ts": datetime.now().strftime("%H:%M:%S"),
             "result": result, "selected": chat_artifacts or []}
    new_history = ((history or []) + [entry])[-15:]        # cap the session history
    collapsed = [e.get("n") for e in (history or [])]      # collapse all priors; the newest stays open
    # The Dashboard tab holds the embedded Databricks AI/BI dashboard (rendered once in build_layout);
    # it is fleet-level and static, so a governed run leaves it untouched (no_update) below.
    # The chat already carries the full LLM narration; the Preview tab uses the DETERMINISTIC concise
    # paragraph (narrative=None) so an Ask does not pay a second LLM narration call (latency). The Studio /
    # Command Center previews keep the LLM paragraph, where they are not on the hot Ask path.
    preview = (render_pm_preview(result, actions=False)
               if result.get("equipment_id") else empty)
    # Append MAX's answer as an assistant turn so the transcript accumulates (the user turn was added
    # by on_chat / on_preview_action). chat-history re-renders from chat-messages via render_chat_transcript.
    msgs = (messages or []) + [{"role": "assistant", "summary": result.get("chat_summary", "")}]
    # Both the Artifacts and Governance-Trace stacks open the newest + collapse priors.
    return (render_context_bar(result), msgs, new_history, collapsed, collapsed, no_update, preview)


@app.callback(
    Output("tab-artifacts", "children"),
    Input("artifacts-history", "data"),
    Input("artifacts-collapsed", "data"),
)
def render_history(history, collapsed):
    """Render the Artifacts tab as the accumulated history stack (newest first, collapsible)."""
    return render_artifact_history(history or [], collapsed or [])


@app.callback(
    Output("tab-trace", "children"),
    Input("artifacts-history", "data"),
    Input("trace-collapsed", "data"),
)
def render_trace(history, collapsed):
    """Render the Governance Trace tab as a history stack over the SAME per-answer results (model tool
    plan + full deterministic tool trace + scoped SQL), newest first, collapsible."""
    return render_trace_history(history or [], collapsed or [])


@app.callback(
    Output("artifacts-collapsed", "data", allow_duplicate=True),
    Input({"type": "arti-hdr", "n": ALL}, "n_clicks"),
    State("artifacts-collapsed", "data"),
    prevent_initial_call=True,
)
def toggle_artifact_card(_clicks, collapsed):
    """Collapse/expand one history card when its header is clicked (dynamically-created buttons fire on
    creation with n_clicks=0 - guard on the fired value so a real click is required)."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    n = trig.get("n")
    s = set(collapsed or [])
    s.discard(n) if n in s else s.add(n)
    return list(s)


@app.callback(
    Output("trace-collapsed", "data", allow_duplicate=True),
    Input({"type": "trace-hdr", "n": ALL}, "n_clicks"),
    State("trace-collapsed", "data"),
    prevent_initial_call=True,
)
def toggle_trace_card(_clicks, collapsed):
    """Collapse/expand one governance-trace card independently of the Artifacts stack."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    n = trig.get("n")
    s = set(collapsed or [])
    s.discard(n) if n in s else s.add(n)
    return list(s)


@app.callback(
    Output("chat-messages", "data"),
    Output("asset-dropdown", "value", allow_duplicate=True),
    Output("time-window", "value", allow_duplicate=True),
    Output("review-type", "value", allow_duplicate=True),
    Output("chat-question", "data"),
    Output("chat-artifacts", "data"),
    Output("chat-input", "value"),  # clear the input after Ask (blank box, standard chat UX)
    Input("chat-send", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    State("session-id", "data"),
    State("chat-messages", "data"),
    prevent_initial_call=True,
)
def on_chat(_clicks, _submit, text, session_id, messages):
    text = (text or "").strip()
    if not text:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update
    # Show the "MAX is thinking" indicator immediately (before the run starts).
    _prog_start(session_id or "ui")
    # Finance-style entity extraction: the model reads the chat and proposes typed entities that scope
    # the run (equipment_id, time_window, review_type) AND selects the visual artifacts the answer
    # needs; the deterministic resolver + closed vocabularies are the fail-closed floor (entities.py).
    ent = agent.extract_entities(text)
    eid = ent.get("equipment_id")
    tw = ent.get("time_window") or no_update
    rt = ent.get("review_type") or no_update
    # Append the user's question so the transcript accumulates (Finance-agent pattern); on_context then
    # appends MAX's answer. The box is cleared ("") and chat-question triggers the governed run.
    msgs = (messages or []) + [{"role": "user", "content": text}]
    return msgs, (eid or no_update), tw, rt, text, ent.get("artifacts") or [], ""  # "" clears chat-input


# Re-render the whole Ask MAX transcript whenever the message store changes (Finance-agent pattern):
# on_chat / on_preview_action append the user turn and on_context appends MAX's answer, so past Q&A
# stay stacked (oldest -> newest) instead of overwriting a single slot.
@app.callback(
    Output("chat-history", "children"),
    Input("chat-messages", "data"),
)
def render_chat_transcript(messages):
    return render_transcript(messages or [])


# Auto-scroll the transcript to the newest turn on every append (like Claude / ChatGPT). Clientside so
# there is no server round-trip; the small delay lets Dash paint the new bubble before we scroll.
app.clientside_callback(
    "function(_m){ setTimeout(function(){ var el = document.getElementById('chat-scroll');"
    " if (el) { el.scrollTop = el.scrollHeight; } }, 60); return ''; }",
    Output("chat-scroll-anchor", "children"),
    Input("chat-messages", "data"),
    prevent_initial_call=True,
)


# --- Command Center interactions ----------------------------------------------
@app.callback(
    Output("cc-queue-download", "data"),
    Input("cc-queue-download-btn", "n_clicks"),
    State("pmhealth-table", "derived_virtual_data"),  # rows as currently filtered/sorted in the table
    State("pmhealth-table", "data"),
    prevent_initial_call=True,
)
def download_queue(n_clicks, filtered_rows, all_rows):
    """Export the PM Health queue to CSV - the rows as currently shown (native column filters + sort)."""
    if not n_clicks:
        return no_update
    from max_agent.ui.artifact_catalog import _detail_csv
    from max_agent.ui.command_center import QUEUE_EXPORT_COLUMNS, QUEUE_EXPORT_LABELS
    rows = filtered_rows if filtered_rows is not None else (all_rows or [])
    csv_text = _detail_csv(QUEUE_EXPORT_COLUMNS, QUEUE_EXPORT_LABELS, rows)
    return dcc.send_string(csv_text, "pm_health_review_queue.csv")


def _summarize_pm(eid):
    """Run the AI summarization for a PM and render its preview slide-over."""
    result = agent.run(eid)
    return render_pm_preview(result, narrative=agent.preview_narrative(result, concise=True))


# The busy overlay is shown while either the row-click or the retry callback is in flight, then reset
# when the call resolves (on success AND on error, so it never sticks). The overlay covers the viewport
# and intercepts every click, so a second row-click cannot start a duplicate request. Retry lives in its
# own callback because its Input (cc-retry-btn) only exists after an error renders it - mixing a
# not-yet-present Input into the row-click callback (which fires on the always-present active_cell)
# trips a Dash "nonexistent object" error.
_BUSY_RUNNING = (Output("busy-overlay", "style", allow_duplicate=True), {"display": "flex"}, {"display": "none"})


@app.callback(
    Output("cc-preview", "children"),
    Output("asset-dropdown", "value", allow_duplicate=True),
    Output("workspace", "data", allow_duplicate=True),
    Output("cc-last-eid", "data"),
    Input("pmhealth-table", "active_cell"),
    State("pmhealth-table", "data"),
    running=[_BUSY_RUNNING],
    prevent_initial_call=True,
)
def on_queue_click(active_cell, data):
    """Row body -> PM preview slide-over (runs the AI summarization). Asset/PM link -> Studio.
    A failed summarization renders an inline error+Retry panel (the overlay never sticks)."""
    if not active_cell or not data:
        return no_update, no_update, no_update, no_update
    row = active_cell.get("row")
    if row is None or row >= len(data):
        return no_update, no_update, no_update, no_update
    eid = data[row].get("equipment_id")
    if active_cell.get("column_id") in ("equipment_id", "pm_id"):
        return no_update, eid, "studio", no_update  # asset / PM name -> Work Strategy Studio directly
    try:
        return _summarize_pm(eid), eid, no_update, eid
    except Exception:
        return render_pm_error(eid), eid, no_update, eid


@app.callback(
    Output("cc-preview", "children", allow_duplicate=True),
    Input("cc-retry-btn", "n_clicks"),
    State("cc-last-eid", "data"),
    running=[_BUSY_RUNNING],
    prevent_initial_call=True,
)
def on_pm_retry(n_clicks, last_eid):
    """Retry the summarization for the last-attempted PM (the error panel's Retry button)."""
    if not n_clicks or not last_eid:
        return no_update
    try:
        return _summarize_pm(last_eid)
    except Exception:
        return render_pm_error(last_eid)


@app.callback(
    Output("workspace", "data", allow_duplicate=True),
    Output("cc-preview", "children", allow_duplicate=True),
    Output("chat-question", "data", allow_duplicate=True),
    Output("chat-messages", "data", allow_duplicate=True),
    Input("cc-ask-btn", "n_clicks"),
    Input("cc-studio-btn", "n_clicks"),
    Input("cc-preview-close", "n_clicks"),
    State("asset-dropdown", "value"),
    State("session-id", "data"),
    State("chat-messages", "data"),
    prevent_initial_call=True,
)
def on_preview_action(ask, studio, close, asset, session_id, messages):
    trig = ctx.triggered_id
    # Guard on n_clicks so the dynamically-created buttons don't fire on creation (n_clicks=0).
    if trig == "cc-ask-btn" and ask:
        # Land in Ask MAX with a governed starter question already asked for this PM.
        q = f"Is the PM on {asset} effective, and should anything change?"
        _prog_start(session_id or "ui")
        msgs = (messages or []) + [{"role": "user", "content": q}]
        return "ask", no_update, q, msgs
    if trig == "cc-studio-btn" and studio:
        return "studio", no_update, no_update, no_update
    if trig == "cc-preview-close" and close:
        return no_update, html.Div(), no_update, no_update  # clear the slide-over
    return no_update, no_update, no_update, no_update


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
    Output("studio-body", "children"),
    Input("workspace", "data"),
    Input("asset-dropdown", "value"),
    Input("time-window", "value"),
    Input("review-type", "value"),
    State("approval-audit", "data"),
    prevent_initial_call=True,
)
def on_studio(workspace, equipment_id, time_window, review_type, audit):
    """Fill the Work Strategy Studio for the selected scope. Studio is standalone: its own Asset / Time
    window / Review type filters drive the governed review directly (a Command Center drill-in or a chat
    just set the same shared dropdowns). Renders only when Studio is on screen so the run/narrative cost
    is not paid while browsing another workspace."""
    if workspace != "studio":
        return no_update
    if not equipment_id:
        return render_studio(None)
    result = agent.run(equipment_id, actor=_current_actor(), time_window=time_window, review_type=review_type)
    return render_studio(result, audit=audit or [], narrative=agent.preview_narrative(result))


# (inline button type -> UI action label, canonical workflow transition).
_INLINE_APPROVAL_MAP = {
    "ff-approve": ("APPROVE", "ANALYST_REVIEWED"),
    "ff-request": ("REQUEST_CHANGES", "CHANGES_REQUESTED"),
    "ff-reject": ("REJECT", "REJECTED"),
}


def _run_approval_action(equipment_id, action, transition, comment, audit):
    """Route an approval click through the deterministic approval_workflow_state tool (a click is NOT
    authorization). Returns (new_audit, entry, authorized). Shared by the Studio buttons (on_approval) and
    the inline chat buttons (on_inline_approval). Draft-only; MAX never writes SAP."""
    from datetime import datetime, timezone

    from max_agent.tools import approval_workflow_state
    actor = _current_actor()
    asset = agent._fleet_index.get(equipment_id, {})
    r = agent.run(equipment_id)
    wf = approval_workflow_state(
        package_id=f"PKG-{equipment_id}", current_state="DRAFT", requested_transition=transition,
        # The package drafts MAX's RECOMMENDATION, so the approval follows the recommendation's gate
        # (package_gate_status), NOT the change-under-review gate. Binding to the change gate FAILS OPEN
        # when it is more permissive than the package gate (e.g. PUMP-4102: change PASS vs package
        # REVIEW_REQUIRED). The fallback covers the out-of-scope path where the two gates are equal.
        actor=actor, gate_status=r.get("package_gate_status") or r.get("gate_status"),
        readiness=asset.get("readiness", {}), approval_state=asset.get("approval_state", {}),
        creator_user_id="analyst-09",
    ).get("data", {})
    authorized = bool(wf.get("transition_allowed"))
    entry = {
        "equipment_id": equipment_id, "action": action, "actor": actor.get("user_id"),
        "comment": (comment or "").strip(),
        "outcome": "AUTHORIZED" if authorized else "DENIED",
        "reason": None if authorized else (wf.get("blocked_transition_reason") or "role not verified"),
        "role_verified": bool(wf.get("role_verified")),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return (audit or []) + [entry], entry, authorized


@app.callback(
    Output("approval-audit", "data"),
    Output("approval-trail", "children"),
    Input("approve-btn", "n_clicks"),
    Input("request-btn", "n_clicks"),
    Input("reject-btn", "n_clicks"),
    State("approval-comment", "value"),
    State("asset-dropdown", "value"),
    State("approval-audit", "data"),
    prevent_initial_call=True,
)
def on_approval(a, r_, j, comment, equipment_id, audit):
    mapping = {
        "approve-btn": ("APPROVE", "ANALYST_REVIEWED"),
        # (UI action label, canonical workflow transition). "Request changes" drives the
        # CHANGES_REQUESTED state; the label REQUEST_CHANGES keys the audit badge colour.
        "request-btn": ("REQUEST_CHANGES", "CHANGES_REQUESTED"),
        "reject-btn": ("REJECT", "REJECTED"),
    }
    trig = mapping.get(ctx.triggered_id)
    # Guard on n_clicks so the buttons don't fire on creation (studio re-render gives them n_clicks=0).
    if not trig or not {"approve-btn": a, "request-btn": r_, "reject-btn": j}.get(ctx.triggered_id):
        return no_update, no_update
    action, transition = trig
    new_audit, _entry, _auth = _run_approval_action(equipment_id, action, transition, comment, audit)
    # Refresh the trail in place so the reviewer sees the governed outcome without a full Studio re-render.
    return new_audit, _audit_trail(new_audit, equipment_id)


@app.callback(
    Output("chat-messages", "data", allow_duplicate=True),
    Output("approval-audit", "data", allow_duplicate=True),
    Input({"type": "ff-approve", "key": ALL}, "n_clicks"),
    Input({"type": "ff-request", "key": ALL}, "n_clicks"),
    Input({"type": "ff-reject", "key": ALL}, "n_clicks"),
    State("chat-messages", "data"),
    State("approval-audit", "data"),
    prevent_initial_call=True,
)
def on_inline_approval(_a, _r, _j, messages, audit):
    """Inline chat approve/reject: the human clicks a button MAX surfaced in the transcript. A click is
    NOT authorization - it routes through _run_approval_action (approval_workflow_state: role + gate +
    self-approval + audit) and records the outcome as a chat turn + an audit entry. Draft-only; never SAP."""
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or trig.get("type") not in _INLINE_APPROVAL_MAP:
        return no_update, no_update
    # Fire only on a real click (n_clicks truthy), not on a transcript re-render.
    if not any((t or {}).get("value") for t in (ctx.triggered or [])):
        return no_update, no_update
    key = trig.get("key")
    msgs = messages or []
    eid = None
    if isinstance(key, int) and 0 <= key < len(msgs) and msgs[key].get("kind") == "approval":
        eid = msgs[key].get("equipment_id")
    if not eid:
        return no_update, no_update
    action, transition = _INLINE_APPROVAL_MAP[trig["type"]]
    new_audit, entry, authorized = _run_approval_action(eid, action, transition, "", audit)
    outcome = (f"Recorded: **{action}** on {eid} - {'AUTHORIZED' if authorized else 'DENIED'}"
               + (f" ({entry['reason']})" if entry.get("reason") else "")
               + ". Draft-only; MAX did not write SAP.")
    return msgs + [{"role": "assistant", "summary": outcome}], new_audit


@app.callback(
    Output({"type": "detail-body", "art": MATCH}, "children"),
    Output({"type": "detail-status", "art": MATCH}, "children"),
    Input({"type": "detail-filter", "art": MATCH, "col": ALL}, "value"),
    State({"type": "detail-filter", "art": MATCH, "col": ALL}, "id"),
    State({"type": "detail-store", "art": MATCH}, "data"),
    prevent_initial_call=True,
)
def on_detail_filter(values, ids, store):
    """Re-render ONE detail table's body from its per-column filter inputs (MATCH keys it to that table
    only). Filters are case-insensitive substrings, AND-ed across columns. The rows live in the table's
    own dcc.Store, so filtering never re-runs the pipeline or the LLM."""
    from max_agent.ui.artifact_catalog import _build_detail_body, _filter_rows
    if not store:
        return no_update, no_update
    filt = {i["col"]: v for i, v in zip(ids or [], values or []) if v}
    rows, columns = store.get("rows", []), store.get("columns", [])
    filtered = _filter_rows(rows, filt)
    status = f"{len(filtered)} of {len(rows)} record(s)" + (f" match {len(filt)} filter(s)" if filt else "")
    return _build_detail_body(filtered, columns), status


@app.callback(
    Output({"type": "detail-download", "art": MATCH}, "data"),
    Input({"type": "detail-download-btn", "art": MATCH}, "n_clicks"),
    State({"type": "detail-filter", "art": MATCH, "col": ALL}, "value"),
    State({"type": "detail-filter", "art": MATCH, "col": ALL}, "id"),
    State({"type": "detail-store", "art": MATCH}, "data"),
    prevent_initial_call=True,
)
def on_detail_download(n, values, ids, store):
    """Export the CURRENTLY FILTERED rows of this table as CSV (what you see is what you download)."""
    if not n or not store:
        return no_update
    from max_agent.ui.artifact_catalog import _detail_csv, _filter_rows
    filt = {i["col"]: v for i, v in zip(ids or [], values or []) if v}
    rows = _filter_rows(store.get("rows", []), filt)
    art = (ctx.triggered_id or {}).get("art", "detail")
    suffix = "-filtered" if filt else ""
    return dcc.send_string(_detail_csv(store.get("columns", []), store.get("labels", {}), rows), f"{art}{suffix}.csv")


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
