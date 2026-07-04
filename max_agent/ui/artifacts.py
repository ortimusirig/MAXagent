"""Artifact tab renderers: Decision, Evidence, PM Health, Comparison, SAP Package, Tool Trace."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from dash import dcc, html

from .charts import criticality_figure, gate_status_figure
from .theme import CARD, COLORS, H2, LABEL_COLORS, MUTED, STATUS_COLORS


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


# RAG -> color for execution-readiness badges.
_RAG_COLORS = {"GREEN": "#1a7f37", "YELLOW": "#b7791f", "RED": "#b42318", "NOT_REQUIRED": COLORS["muted"]}


def _rag_badge(color: str) -> html.Span:
    return badge(color or "-", _RAG_COLORS.get(color, COLORS["muted"]))


# --- Decision ---------------------------------------------------------------
def render_decision(r: Dict[str, Any]) -> html.Div:
    gate = r.get("gate_status", "-")
    label = r.get("classifier_label", "-")
    reason = r.get("gate_reason") or r.get("gate_review_trigger") or ""
    return html.Div([
        html.Div([
            html.Div("Effectiveness", style=MUTED),
            badge(label, LABEL_COLORS.get(label, COLORS["muted"])),
            html.Span("  do-not-optimize" if r.get("do_not_optimize") else "", style={"fontSize": "12px", "color": "#6b46c1", "marginLeft": "8px"}),
        ], style=CARD),
        html.Div([
            html.Div("Governance gate", style=MUTED),
            badge(gate, STATUS_COLORS.get(gate, COLORS["muted"])),
            html.Div(reason, style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "6px"}),
        ], style=CARD),
        html.Div([
            html.Div("MAX recommendation", style=H2),
            _kv("Type", r.get("recommendation_type")),
            _kv("Rationale", r.get("recommendation_rationale")),
            _kv("Next action", r.get("recommendation_next_action")),
        ], style=CARD),
        html.Div([
            html.Div("Approvals and next actions", style=H2),
            _kv("Required approvers", ", ".join(r.get("required_approvers") or []) or "none named yet"),
            html.Div("Allowed next:", style={"fontSize": "12px", "color": COLORS["muted"], "marginTop": "6px"}),
            _bullets(r.get("allowed_next_actions")),
            html.Div("Blocked:", style={"fontSize": "12px", "color": COLORS["muted"]}),
            _bullets(r.get("blocked_actions")),
        ], style=CARD),
    ])


# --- Evidence ---------------------------------------------------------------
# (readiness tool -> display label, RAG key in that tool's data)
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
    # planned-hours calibration is not RAG - it flags LOW confidence and routes to SME.
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
    ])


# --- PM Health --------------------------------------------------------------
def render_pm_health(health: Dict[str, Any]) -> html.Div:
    # Backward-compat: accept either the composed health dict or a bare rows list.
    if isinstance(health, list):
        health = {"rows": health, "triage": {}, "metrics": {}, "kpis": {}}
    rows = health.get("rows", [])
    metrics = health.get("metrics", {})
    triage = health.get("triage", {})
    kpis = (health.get("kpis") or {}).get("kpis", [])

    by_gate = metrics.get("by_gate_status", {})
    # Ranked triage queue (pm_portfolio_triage); fall back to raw rows if absent.
    queue = triage.get("queue") or [
        {"rank": i + 1, "equipment_id": r.get("equipment_id"), "criticality": r.get("criticality"),
         "label": r.get("label"), "gate_status": r.get("gate_status"), "reason": r.get("gate_reason")}
        for i, r in enumerate(rows)
    ]
    triage_rows = [[
        q.get("rank"), q.get("equipment_id"), q.get("criticality"), q.get("label"),
        badge(q.get("gate_status"), STATUS_COLORS.get(q.get("gate_status"), COLORS["muted"])),
        q.get("reason"),
    ] for q in queue]
    kpi_rows = [[k.get("kpi"), k.get("unit"), k.get("basis"), "-" if k.get("value") is None else k.get("value")] for k in kpis]

    return html.Div([
        html.Div([
            dcc.Graph(figure=gate_status_figure(rows), config={"displayModeBar": False}),
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
            html.Div("Counts only - no realized-savings or effectiveness score implied (thresholds null / value baseline-only).", style=MUTED),
        ], style=CARD),
        html.Div([
            html.Div("Portfolio triage (pm_portfolio_triage - attention first)", style=H2),
            _table(["#", "Asset", "Crit", "Label", "Gate", "Reason"], triage_rows),
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
        # Out-of-scope assets short-circuit before the Wave-B comparison runs.
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


# --- SAP Package ------------------------------------------------------------
def render_sap_package(r: Dict[str, Any]) -> html.Div:
    p = r.get("package", {})
    ak = p.get("attachment_k", {})
    deferred = p.get("deferred_fields", [])
    cv = p.get("current_value")
    pv = p.get("proposed_value")
    cv = cv.get("value") if isinstance(cv, dict) else cv
    pv = pv.get("value") if isinstance(pv, dict) else pv
    return html.Div([
        html.Div([
            html.Div("DRAFT ONLY - MAX does not write to SAP in Wave 1. A human approves; MDC/BPDO or the official Oxy process updates SAP.",
                     style={"background": "#fff4e5", "border": "1px solid #f0c987", "borderRadius": "8px", "padding": "10px", "fontSize": "13px", "color": "#8a5a00", "marginBottom": "12px"}),
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


# --- Tool Trace -------------------------------------------------------------
def render_tool_trace(r: Dict[str, Any]) -> html.Div:
    trace = r.get("tool_trace", [])
    rows = [[
        t.get("tool"),
        badge(t.get("status"), {"success": "#1a7f37", "warning": "#b7791f", "blocked": "#b42318", "error": "#b42318"}.get(t.get("status"), COLORS["muted"])),
        t.get("blocked_reason") or "",
        t.get("summary"),
    ] for t in trace]
    return html.Div([
        html.Div([
            html.Div("Tool Trace (deterministic pipeline)", style=H2),
            html.Div(f"Databricks mode: {r.get('databricks_mode')}", style=MUTED),
            _table(["Tool", "Status", "Reason", "Summary"], rows),
        ], style=CARD),
    ])
