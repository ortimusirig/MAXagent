"""Artifact renderers: Context bar, conversation pills, and the six artifact tabs
(Decision, Evidence, PM Health, Comparison, SAP Package, Tool Trace) per 60/04 + 30/AppExp."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from dash import dash_table, dcc, html

from .charts import criticality_figure, data_readiness_figure, gate_status_figure
from .theme import CARD, COLORS, H2, LABEL_COLORS, MUTED, RAG_COLORS, STATUS_COLORS


def badge(text: str, color: str) -> html.Span:
    return html.Span(
        text or "-",
        style={
            "display": "inline-block", "padding": "3px 10px", "borderRadius": "999px",
            "background": color, "color": "white", "fontSize": "12px", "fontWeight": 700,
        },
    )


def _kv(label: str, value: Any) -> html.Div:
    return html.Div(
        [html.Span(label + ": ", style={"fontWeight": 600, "color": COLORS["ink"]}),
         html.Span(str(value), style={"color": COLORS["muted"]})],
        style={"fontSize": "13px", "margin": "3px 0"},
    )


def _table(headers: List[str], rows: List[List[Any]]) -> html.Table:
    thead = html.Thead(html.Tr([html.Th(h, style={"textAlign": "left", "padding": "6px 10px", "borderBottom": f"2px solid {COLORS['line']}", "fontSize": "12px", "color": COLORS["muted"]}) for h in headers]))
    trs = []
    for r in rows:
        trs.append(html.Tr([html.Td(c, style={"padding": "6px 10px", "borderBottom": f"1px solid {COLORS['line']}", "fontSize": "13px"}) for c in r]))
    return html.Table([thead, html.Tbody(trs)], style={"width": "100%", "borderCollapse": "collapse"})


def _bullets(items: List[str]) -> html.Ul:
    return html.Ul([html.Li(i, style={"fontSize": "13px", "margin": "2px 0"}) for i in (items or ["-"])], style={"margin": "4px 0", "paddingLeft": "18px"})


def _rag_badge(color: str) -> html.Span:
    return badge(color or "-", RAG_COLORS.get(color, COLORS["muted"]))


def _chip(label: str, value: str) -> html.Span:
    return html.Span(
        [html.Span(label + " ", style={"color": COLORS["muted"], "fontSize": "11px"}),
         html.Span(str(value if value not in (None, "") else "-"), style={"color": COLORS["ink"], "fontWeight": 700, "fontSize": "12px"})],
        style={"background": COLORS["chip"], "borderRadius": "8px", "padding": "4px 9px", "marginRight": "8px", "marginBottom": "6px", "display": "inline-block"},
    )


# --- Top context bar (60/04, 30/AppExp) -------------------------------------
def render_context_bar(r: Dict[str, Any]) -> html.Div:
    if not r or r.get("error"):
        return html.Div()
    op = r.get("operated_status")
    ex = r.get("exemption_status")
    if op == "OPERATED" and ex in (None, "NONE"):
        scope_note = "operated / in scope"
    else:
        scope_note = f"OUT OF SCOPE ({op or ex})"
    crit = (str(r.get("criticality_code") or "-") + " " + str(r.get("criticality_label") or "")).strip()
    chips = [
        _chip("Asset", r.get("equipment_id")),
        _chip("Class", r.get("asset_class")),
        _chip("Plant", r.get("plant")),
        _chip("Criticality", crit),
        _chip("Time window", r.get("time_window")),
        _chip("Review", r.get("review_type")),
        _chip("BU profile", r.get("bu_profile_id")),
        _chip("Scope", scope_note),
    ]
    return html.Div(chips, style={"padding": "10px 22px", "borderBottom": f"1px solid {COLORS['line']}", "background": "#fbfdff"})


# --- Conversation tool pills (60/04) ----------------------------------------
_PILL_COLOR = {"success": "#1a7f37", "warning": "#b7791f", "blocked": "#b42318", "error": "#b42318"}


def render_pills(r: Dict[str, Any]) -> html.Div:
    trace = r.get("tool_trace", []) if r else []
    pills, seen = [], []
    for t in trace:
        name = t.get("tool")
        if not name or name in seen:
            continue
        seen.append(name)
        color = _PILL_COLOR.get(t.get("status"), COLORS["muted"])
        pills.append(html.Span(name, style={
            "display": "inline-block", "border": f"1px solid {color}", "color": color,
            "borderRadius": "999px", "padding": "2px 8px", "margin": "0 6px 6px 0",
            "fontSize": "11px", "fontWeight": 600,
        }))
    if not pills:
        return html.Div()
    return html.Div([
        html.Div("Deterministic tools that decided this (the answer below is narrated)", style={**MUTED, "marginBottom": "4px"}),
        html.Div(pills),
    ], style={"marginBottom": "10px"})


# --- Approval lifecycle strip (60/04 gap 25, 30/AppExp) ---------------------
_LIFECYCLE = ["DRAFT", "ANALYST_REVIEWED", "SME_REVIEWED", "WORK_STRATEGY_OWNER_APPROVED", "MASTER_DATA_SUBMITTED"]


def _lifecycle_strip(current: str) -> html.Div:
    cur = (current or "DRAFT").upper()
    steps = []
    for i, s in enumerate(_LIFECYCLE):
        active = s == cur
        steps.append(html.Span(
            s.replace("_", " ").title(),
            style={
                "fontSize": "11px", "padding": "3px 8px", "borderRadius": "6px", "marginRight": "6px",
                "background": COLORS["oxy"] if active else COLORS["chip"],
                "color": "white" if active else COLORS["muted"], "fontWeight": 700 if active else 500,
            },
        ))
        if i < len(_LIFECYCLE) - 1:
            steps.append(html.Span("->", style={"color": COLORS["muted"], "marginRight": "6px", "fontSize": "11px"}))
    return html.Div(steps, style={"margin": "6px 0"})


# --- Decision ---------------------------------------------------------------
def render_decision(r: Dict[str, Any]) -> html.Div:
    gate = r.get("gate_status", "-")
    label = r.get("classifier_label", "-")
    reason = r.get("gate_reason") or r.get("gate_review_trigger") or ""
    wf = r.get("workflow") or {}
    wf_state = wf.get("current_state") or wf.get("state") or "DRAFT"
    allowed_tx = wf.get("allowed_transitions") or wf.get("allowed") or r.get("allowed_next_actions") or []
    blocked_tx = wf.get("blocked_transitions") or wf.get("blocked") or r.get("blocked_actions") or []
    return html.Div([
        html.Div([
            html.Div("Effectiveness", style=MUTED),
            badge(label, LABEL_COLORS.get(label, COLORS["muted"])),
            html.Span("  do-not-optimize" if r.get("do_not_optimize") else "", style={"fontSize": "12px", "color": "#6b46c1", "marginLeft": "8px"}),
            html.Div([
                html.Span("Confidence: ", style={"fontWeight": 600, "fontSize": "12px", "color": COLORS["ink"]}),
                html.Span(str(r.get("classifier_confidence") or "-"), style={"fontSize": "12px", "color": COLORS["muted"], "marginRight": "14px"}),
                html.Span("Data readiness: ", style={"fontWeight": 600, "fontSize": "12px", "color": COLORS["ink"]}),
                _rag_badge(r.get("data_readiness_rag")),
            ], style={"marginTop": "8px"}),
        ], style=CARD),
        html.Div([
            html.Div("Governance gate", style=MUTED),
            badge(gate, STATUS_COLORS.get(gate, COLORS["muted"])),
            html.Div(reason, style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "6px"}),
        ], style=CARD),
        html.Div([
            html.Div("Change under review vs MAX recommendation", style=H2),
            _kv("Change under review (gated + packaged)", r.get("change_under_review_type")),
            _kv("  gated as", r.get("gate_status")),
            _kv("MAX recommendation", r.get("recommendation_type")),
            _kv("  gated as", r.get("recommendation_gate_status")),
            _kv("Rationale", r.get("recommendation_rationale")),
            _kv("Next action", r.get("recommendation_next_action")),
            html.Div(
                "MAX's recommendation differs from the change under review: MAX advises the recommendation above, "
                "and it is gate-checked separately. The SAP Package drafts the change under review.",
                style={"background": "#fff4e5", "border": "1px solid #f0c987", "borderRadius": "8px",
                       "padding": "8px", "fontSize": "12px", "color": "#8a5a00", "marginTop": "6px"},
            ) if r.get("recommendation_diverges") else html.Div(),
        ], style=CARD),
        html.Div([
            html.Div("Approval workflow (draft-only, Wave 1)", style=H2),
            _kv("Current state", wf_state),
            _lifecycle_strip(wf_state),
            _kv("Required approvers", ", ".join(r.get("required_approvers") or []) or "none named yet"),
            html.Div("Allowed next:", style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "6px"}),
            _bullets(allowed_tx),
            html.Div("Blocked:", style={"fontSize": "12px", "color": COLORS["muted"]}),
            _bullets(blocked_tx),
            html.Div("Approver identity comes from Databricks sign-in; a typed name is never accepted as authorization. Use the SAP Package tab to record a governed action.", style=MUTED),
        ], style=CARD),
    ])


# --- Evidence ---------------------------------------------------------------
_READINESS_DISPLAY = [
    ("task_list_bom_readiness", "Task list / object dependency", "task_list_readiness"),
    ("materials_component_readiness", "Materials / BOM", "material_readiness"),
    ("procurement_readiness", "Procurement / lead time", "procurement_readiness"),
    ("contractor_service_readiness", "Contractor / service source", "contractor_readiness"),
    ("cbm_measurement_readiness", "CBM measurement (fails closed)", "cbm_readiness"),
]


def _readiness_card(r: Dict[str, Any]) -> html.Div:
    checks = r.get("readiness_checks") or {}
    if not checks:
        return html.Div()
    rows = []
    for tool, label, rag_key in _READINESS_DISPLAY:
        data = checks.get(tool, {})
        rows.append([label, _rag_badge(data.get(rag_key))])
    ph = checks.get("planned_hours_calibration", {})
    ph_note = ph.get("calibration", "-")
    if ph.get("confidence_flag"):
        ph_note = f"{ph_note} ({ph['confidence_flag']} confidence -> {ph.get('route', 'SME')})"
    rows.append(["Planned-hours calibration", ph_note])
    children = [
        html.Div("Execution readiness (Wave C)", style=H2),
        _table(["Check", "Status"], rows),
        html.Div("ABC-4 needs a Table 2 object dependency; CBM fails closed without real readings; absent actuals are not penalized.", style=MUTED),
    ]
    trial = r.get("trial")
    if trial:
        children.append(html.Div([
            html.Div("Trial monitor: ", style={"fontWeight": 600, "display": "inline", "color": COLORS["ink"]}),
            badge(trial.get("decision"), {"STOP": "#b42318"}.get(trial.get("decision"), "#1a7f37")),
            html.Span("  " + str(trial.get("reason", "")), style={"fontSize": "12px", "color": COLORS["muted"]}),
        ], style={"marginTop": "10px"}))
    return html.Div(children, style=CARD)


def render_evidence(r: Dict[str, Any]) -> html.Div:
    ev = r.get("evidence", {})
    wo = ev.get("work_order_history", [])
    cost = (ev.get("cost_summary") or [{}])[0]
    findings = (ev.get("notification_findings") or [{}])[0]
    # Scoped SQL preview (from the Tool Trace) so the Evidence tab shows the query was scoped.
    sql_previews = []
    for t in r.get("tool_trace", []):
        if t.get("tool") in ("run_scoped_sql", "genie_query_scoped"):
            d = t.get("data", {})
            preds = d.get("scope_predicates") or d.get("referenced_relations")
            sql_previews.append(f"{t.get('tool')}: {d.get('template_name') or d.get('generated_sql') or '(scoped)'} | scope={preds}")
    return html.Div([
        html.Div([
            html.Div("Work-order mix (synthetic, scoped)", style=H2),
            _table(["Order type", "Count"], [[w.get("order_type"), w.get("n")] for w in wo]) if wo else html.Div("no rows", style=MUTED),
        ], style=CARD),
        html.Div([
            html.Div("Cost (honest view)", style=H2),
            _kv("Labor cost", cost.get("labor_cost")),
            _kv("Material/services cost", cost.get("material_cost")),
            _kv("Basis", cost.get("basis")),
            html.Div("Labor cost is 0 in the sample - no labor-savings claim is defensible (F1).", style=MUTED),
        ], style=CARD),
        html.Div([
            html.Div("Findings coding", style=H2),
            _kv("Damage coded", findings.get("damage_coded_pct")),
            _kv("Cause coded", findings.get("cause_coded_pct")),
        ], style=CARD),
        _readiness_card(r),
        html.Div([
            html.Div("Scoped retrieval (query preview)", style=H2),
            _bullets(sql_previews) if sql_previews else html.Div("-", style=MUTED),
            html.Div("Every query carries the locked scope; Genie SQL also passes the SELECT-only + view-allowlist safety guard.", style=MUTED),
        ], style=CARD),
    ])


# --- PM Health (queue-first, drill-through) ---------------------------------
def render_pm_health(health: Dict[str, Any]) -> html.Div:
    if isinstance(health, list):
        health = {"rows": health, "triage": {}, "metrics": {}, "kpis": {}}
    rows = health.get("rows", [])
    metrics = health.get("metrics", {})
    triage = health.get("triage", {})
    kpis = (health.get("kpis") or {}).get("kpis", [])

    by_gate = metrics.get("by_gate_status", {})
    readiness_by_id = {r.get("equipment_id"): r.get("data_readiness") for r in rows}
    next_by_id = {r.get("equipment_id"): r.get("next_action") for r in rows}
    queue = triage.get("queue") or [
        {"rank": i + 1, "equipment_id": r.get("equipment_id"), "criticality": r.get("criticality"),
         "label": r.get("label"), "gate_status": r.get("gate_status"), "reason": r.get("gate_reason")}
        for i, r in enumerate(rows)
    ]
    table_data = [{
        "rank": q.get("rank"), "equipment_id": q.get("equipment_id"), "criticality": q.get("criticality"),
        "data_readiness": readiness_by_id.get(q.get("equipment_id"), "-"),
        "label": q.get("label"), "gate_status": q.get("gate_status"), "reason": q.get("reason"),
        "next_action": next_by_id.get(q.get("equipment_id"), "-"),
    } for q in queue]

    style_cond = []
    for status, color in STATUS_COLORS.items():
        style_cond.append({"if": {"filter_query": f'{{gate_status}} = "{status}"', "column_id": "gate_status"}, "backgroundColor": color, "color": "white"})
    for rag, color in RAG_COLORS.items():
        style_cond.append({"if": {"filter_query": f'{{data_readiness}} = "{rag}"', "column_id": "data_readiness"}, "backgroundColor": color, "color": "white"})

    table = dash_table.DataTable(
        id="pmhealth-table",
        columns=[
            {"name": "#", "id": "rank"}, {"name": "Asset", "id": "equipment_id"},
            {"name": "Crit", "id": "criticality"}, {"name": "Data readiness", "id": "data_readiness"},
            {"name": "Label", "id": "label"}, {"name": "Gate", "id": "gate_status"}, {"name": "Reason", "id": "reason"},
            {"name": "Recommended next action", "id": "next_action"},
        ],
        data=table_data,
        cell_selectable=True, page_size=20,
        style_cell={"fontFamily": "inherit", "fontSize": "12px", "padding": "6px 8px", "textAlign": "left", "whiteSpace": "normal", "height": "auto"},
        style_header={"fontWeight": 700, "color": COLORS["muted"], "backgroundColor": "#fbfdff", "border": "none", "borderBottom": f"2px solid {COLORS['line']}"},
        style_data={"border": "none", "borderBottom": f"1px solid {COLORS['line']}"},
        style_data_conditional=style_cond,
    )
    kpi_rows = [[k.get("kpi"), k.get("unit"), k.get("basis"), "-" if k.get("value") is None else k.get("value")] for k in kpis]

    return html.Div([
        html.Div([
            html.Div("PM Health review queue (queue-first - click a row to open it in the tabs)", style=H2),
            html.Div("Highest-attention PMs first (BLOCKED / governance / review). Selecting a row locks that asset's context across every tab.", style=MUTED),
            table,
        ], style=CARD),
        html.Div([
            dcc.Graph(figure=gate_status_figure(rows), config={"displayModeBar": False}),
            dcc.Graph(figure=data_readiness_figure(rows), config={"displayModeBar": False}),
            dcc.Graph(figure=criticality_figure(rows), config={"displayModeBar": False}),
        ], style=CARD),
        html.Div([
            html.Div("PM health metrics (pm_health_dashboard_metrics)", style=H2),
            _kv("Population", metrics.get("population_count", len(rows))),
            _kv("Blocked", by_gate.get("BLOCKED", 0)),
            _kv("Review-required", by_gate.get("REVIEW_REQUIRED", 0)),
            _kv("Draft-only", by_gate.get("DRAFT_ONLY", 0)),
            _kv("Pass", by_gate.get("PASS", 0)),
            _kv("Do-not-optimize", metrics.get("do_not_optimize_count", 0)),
            html.Div("Counts only - no realized-savings or effectiveness score implied (thresholds null / value baseline-only). Synthetic-data mode.", style=MUTED),
        ], style=CARD),
        html.Div([
            html.Div("Value KPIs (value_kpi_tracker - baseline only)", style=H2),
            _table(["KPI", "Unit", "Basis", "Value"], kpi_rows) if kpi_rows else html.Div("-", style=MUTED),
            html.Div("Savings claims are not allowed: labor cost is 0 in the sample; avoided hours/cost are not computable (F1).", style=MUTED),
        ], style=CARD),
    ])


# --- Comparison -------------------------------------------------------------
def render_comparison(r: Dict[str, Any]) -> html.Div:
    change_card = html.Div([
        html.Div("Change under consideration", style=H2),
        _kv("Current", r.get("proposed_summary", "").split(" -> ")[0] if r.get("proposed_summary") else "-"),
        _kv("Proposed", r.get("proposed_summary", "").split(" -> ")[-1] if r.get("proposed_summary") else "-"),
    ], style=CARD)

    cmp = r.get("comparison_result")
    if not cmp:
        return html.Div([
            change_card,
            html.Div([
                html.Div("Like-equipment comparison", style=H2),
                html.Div("Comparison is skipped for out-of-scope assets (scope fails closed before Wave-B tools run).", style=MUTED),
            ], style=CARD),
        ])

    target = cmp.get("target", {})
    cohort = cmp.get("cohort", [])
    candidates = cmp.get("standardization_candidates", [])

    def _row_cells(row: Dict[str, Any]) -> List[Any]:
        return [row.get("equipment_id"), row.get("strategy_type"), row.get("cycle"),
                row.get("package"), row.get("planned_hours"), row.get("work_center")]

    headers = ["Asset", "Strategy", "Cycle", "Package", "Planned hrs", "Work ctr"]
    cohort_rows = [_row_cells(c) for c in cohort]
    target_row = [_row_cells(target)] if target.get("equipment_id") else []

    return html.Div([
        change_card,
        html.Div([
            html.Div(f"Like-equipment cohort for {target.get('equipment_id', '-')} (like_equipment_matcher)", style=H2),
            html.Div("Target", style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "4px"}),
            _table(headers, target_row) if target_row else html.Div("-", style=MUTED),
            html.Div("Cohort (same asset class)", style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "10px"}),
            _table(headers, cohort_rows) if cohort_rows else html.Div("no like equipment in the synthetic fleet", style=MUTED),
        ], style=CARD),
        html.Div([
            html.Div("Standardization candidates (pm_comparison_engine)", style=H2),
            _bullets([f"{c} differs on strategy/cycle" for c in candidates]) if candidates else html.Div("cohort is already aligned on strategy/cycle", style=MUTED),
            html.Div("Standardization is a draft recommendation; each change still clears oxy_gate_check and is human-approved.", style=MUTED),
        ], style=CARD),
    ])


# --- SAP Package (+ governed approve/reject/request-change) ------------------
def _audit_trail(audit: List[Dict[str, Any]], equipment_id: str) -> html.Div:
    entries = [a for a in (audit or []) if a.get("equipment_id") == equipment_id]
    if not entries:
        return html.Div("No governed actions recorded this session.", style=MUTED)
    rows = []
    for e in entries:
        outcome = e.get("outcome", "AUTHORIZED")
        outcome_cell = badge(outcome, "#1a7f37" if outcome == "AUTHORIZED" else "#b42318")
        detail = e.get("reason") or e.get("comment") or ""
        rows.append([
            e.get("timestamp"), e.get("actor"),
            badge(e.get("action"), {"REJECT": "#b42318", "REQUEST_CHANGES": "#b7791f"}.get(e.get("action"), "#0b5cab")),
            outcome_cell, detail,
        ])
    return _table(["When", "Actor", "Action", "Outcome", "Reason / comment"], rows)


def render_sap_package(r: Dict[str, Any], audit: List[Dict[str, Any]] = None) -> html.Div:
    p = r.get("package", {})
    ak = p.get("attachment_k", {})
    deferred = p.get("deferred_fields", [])
    cv = p.get("current_value")
    pv = p.get("proposed_value")
    cv = cv.get("value") if isinstance(cv, dict) else cv
    pv = pv.get("value") if isinstance(pv, dict) else pv
    gate = r.get("gate_status")
    submit_ok = bool(p.get("submit_path_available")) and gate not in ("BLOCKED",)

    btn = {"border": "none", "borderRadius": "8px", "padding": "8px 14px", "marginRight": "8px", "fontWeight": 700, "fontSize": "13px", "cursor": "pointer", "color": "white"}
    controls = html.Div([
        html.Div("Governed action (draft-only; recorded to the session audit trail; never writes SAP)", style=H2),
        dcc.Textarea(id="approval-comment", placeholder="Reviewer comment (optional)", style={"width": "100%", "height": "48px", "marginBottom": "8px", "fontFamily": "inherit", "fontSize": "13px"}),
        html.Div([
            html.Button("Mark reviewed / approve", id="approve-btn", n_clicks=0, disabled=not submit_ok, style={**btn, "background": "#1a7f37" if submit_ok else COLORS["muted"]}),
            html.Button("Request changes", id="request-btn", n_clicks=0, style={**btn, "background": "#b7791f"}),
            html.Button("Reject", id="reject-btn", n_clicks=0, style={**btn, "background": "#b42318"}),
        ]),
        html.Div(
            "Submit path available" if submit_ok else f"Submit path unavailable for gate={gate} (draft stays in review).",
            style={**MUTED, "marginTop": "6px"},
        ),
        html.Div("Governed action (Wave 1)", style={**H2, "marginTop": "14px"}),
        html.Div(id="approval-trail", children=_audit_trail(audit, r.get("equipment_id"))),
    ], style=CARD)

    return html.Div([
        html.Div([
            html.Div("DRAFT ONLY - MAX does not write to SAP in Wave 1. A human approves; MDC/BPDO or the official Oxy process updates SAP.",
                     style={"background": "#fff4e5", "border": "1px solid #f0c987", "borderRadius": "8px", "padding": "10px", "fontSize": "13px", "color": "#8a5a00", "marginBottom": "12px"}),
            html.Div([
                html.Span("This package drafts MAX's recommendation: ", style={"fontWeight": 600, "fontSize": "13px", "color": COLORS["ink"]}),
                html.Span(f"{r.get('recommendation_type')} ", style={"fontSize": "13px", "color": COLORS["ink"], "fontWeight": 700}),
                badge(r.get("package_gate_status"), STATUS_COLORS.get(r.get("package_gate_status"), COLORS["muted"])),
                html.Div(f"Change you asked about: {r.get('change_under_review_type')} - gated as {r.get('gate_status')}."
                         + (" (MAX recommends the above instead.)" if r.get("recommendation_diverges") else ""),
                         style={**MUTED, "marginTop": "4px"}),
            ], style={"marginBottom": "10px"}),
            html.Div("Package", style=H2),
            _kv("Type", p.get("package_type")),
            _kv("Current value", cv),
            _kv("Proposed value", pv),
            _kv("Affected SAP objects", ", ".join(p.get("affected_sap_objects") or [])),
            _kv("Gate", str(p.get("gate_status")) + " / " + str(p.get("gate_reason"))),
            _kv("Synthetic", p.get("synthetic_flag")),
            _kv("Level loading", p.get("level_loading_status")),
            _kv("Writes SAP", p.get("max_writes_sap")),
            _kv("Approval path available", p.get("approval_path_available")),
            _kv("Submit path available", p.get("submit_path_available")),
        ], style=CARD),
        controls,
        html.Div([
            html.Div("Attachment K (Work Strategy Management Worksheet shape)", style=H2),
            _kv("Criticality", (ak.get("criticality") or {}).get("code")),
            _kv("Analysis method", ak.get("analysis_method")),
            _kv("Strategy type", ak.get("strategy_type")),
            _kv("Object dependency", json.dumps(ak.get("object_dependency", {}))),
            _kv("Task list", json.dumps(ak.get("task_list", {}))),
            _kv("Cost/benefit", json.dumps(ak.get("cost_benefit", {}))),
            _kv("MOC linkage", ak.get("moc_linkage")),
            _kv("Master-data request", json.dumps(ak.get("master_data_request", {}))),
            _kv("Attachment K confirmed", ak.get("attachment_k_confirmed")),
        ], style=CARD),
        html.Div([
            html.Div("Deferred / fail-closed fields (Oxy must confirm)", style=H2),
            _table(["Field", "Posture", "Reason"], [[d.get("field"), badge(d.get("posture"), COLORS["muted"]), d.get("reason")] for d in deferred]),
        ], style=CARD),
    ])


# --- Tool Trace (enriched) --------------------------------------------------
def render_tool_trace(r: Dict[str, Any]) -> html.Div:
    trace = r.get("tool_trace", [])
    ctx = f"bu_profile={r.get('bu_profile_id')} | criticality={r.get('criticality_code')} | time_window={r.get('time_window')}"
    rows = []
    for t in trace:
        d = t.get("data", {}) or {}
        detail = d.get("generated_sql") or d.get("template_name") or d.get("gate_status") or ""
        rows.append([
            t.get("tool"),
            badge(t.get("status"), _PILL_COLOR.get(t.get("status"), COLORS["muted"])),
            t.get("confidence") or "-",
            t.get("blocked_reason") or "",
            str(detail)[:60],
            t.get("summary"),
        ])
    return html.Div([
        html.Div([
            html.Div("Tool Trace (deterministic pipeline)", style=H2),
            html.Div(f"Databricks mode: {r.get('databricks_mode')}  |  {ctx}", style=MUTED),
            _table(["Tool", "Status", "Conf", "Reason", "Detail (SQL / template / gate)", "Summary"], rows),
        ], style=CARD),
    ])
