"""Model-selected artifact catalog for the Ask MAX Artifacts tab (per 50 - UI and Experience).

The Artifacts tab shows the VISUAL objects the answer needs - Plotly charts, HTML tables, the
comparison chart, the gate/tool trace - generated per the question's requirement, not a fixed stack.
The model selects which artifacts are relevant (entities.py -> ARTIFACT_CHOICES); this module renders
exactly those, stacked. A deterministic default set is the fail-closed floor when the model selects
nothing valid. Every value is governed (from agent.run(result)); the catalog only chooses the visuals.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
from dash import dcc, html

from ..entities import ARTIFACT_CHOICES
from ..labels import gate_label, rec_label
from .artifacts import _kv, _table, badge, render_comparison, render_governance_trace
from .theme import CARD, COLORS, H2, MUTED, RAG_COLORS, STATUS_COLORS


def _card(title: str, body: Any) -> html.Div:
    return html.Div([html.Div(title, style=H2), body], style=CARD)


def _work_order_mix(result: Dict[str, Any], live: bool = True):
    by_type = (result.get("evidence_digest") or {}).get("work_orders_by_type") or {}
    if not by_type:
        return None
    keys = list(by_type)
    fig = go.Figure(go.Bar(x=keys, y=[by_type[k] for k in keys], marker_color=COLORS["oxy"]))
    fig.update_layout(title="Work-order mix (scoped)", height=260, margin=dict(l=30, r=20, t=40, b=30),
                      paper_bgcolor="white", plot_bgcolor="white", yaxis_title="orders")
    return html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False})], style=CARD)


def _data_readiness(result: Dict[str, Any], live: bool = True):
    rag = result.get("data_readiness") or result.get("data_readiness_rag") or "-"
    needs = result.get("data_needs") or []
    color = RAG_COLORS.get(rag, COLORS["muted"])
    items = [html.Div([html.Span(n.get("need", ""), style={"fontWeight": 600}),
                       html.Span(f"  - SAP: {n.get('sap_source', '')}", style={"color": COLORS["muted"]})],
                      style={"fontSize": "12px", "margin": "3px 0"}) for n in needs]
    return _card("Data readiness", html.Div([
        html.Span(rag, style={"display": "inline-block", "padding": "3px 10px", "borderRadius": "999px",
                              "background": color, "color": "white", "fontSize": "12px", "fontWeight": 700}),
        html.Div("Data still needed to score effectiveness:" if needs else "Required domains present.",
                 style={**MUTED, "marginTop": "8px"}),
        *items,
    ]))


def _reliability(result: Dict[str, Any], live: bool = True):
    """Reliability evidence artifact (tools 25-27): MTBF/MTTR/availability, the Weibull hazard shape +
    P(fail)/RUL, and the top failure modes - with the math-defensible interpretation. Evidence-only."""
    rel = result.get("reliability") or {}
    m, w, fm = rel.get("metrics") or {}, rel.get("weibull") or {}, rel.get("failure_modes") or {}
    if not (m or w or fm):
        return None
    kids = [html.Div("Reliability (evidence - does not change the label or gate)", style=H2)]
    if m.get("computable"):
        kids.append(_table(["Metric", "Value"], [
            ["MTBF (days)", m.get("mtbf_days")], ["MTTR (hours)", m.get("mttr_hours")],
            ["Availability (%)", m.get("availability_pct")], ["Unplanned failures", m.get("n_failures")]]))
    if w.get("computable"):
        rul = w.get("rul_days") or {}
        kids.append(html.Div(f"Hazard shape: {w.get('hazard_shape')} (Weibull beta={w.get('beta')})",
                             style={"fontWeight": 700, "fontSize": "13px", "marginTop": "8px", "color": COLORS["oxy"]}))
        kids.append(_table(["Reliability estimate", "Value"], [
            [f"P(fail in {w.get('horizon_days')}d)", f"{round((w.get('p_fail_horizon') or 0) * 100)}%"],
            ["RUL median (days)", rul.get("rul_p50")], ["RUL early/late (p10/p90)", f"{rul.get('rul_p10')} / {rul.get('rul_p90')}"]]))
    elif w.get("n_failures") is not None:
        kids.append(html.Div(f"Weibull not computed - only {w.get('n_failures')} failure(s) (need {w.get('min_failures')}).", style=MUTED))
    modes = fm.get("modes") or []
    if modes:
        kids.append(html.Div("Failure modes (RCA)", style={**H2, "marginTop": "8px"}))
        kids.append(_table(["Object part / cause", "Count", "Share"],
                           [[f"{md.get('object_part') or '-'} / {md.get('cause_code') or '-'}", md.get("count"), f"{md.get('share_pct')}%"] for md in modes]))
        kids.append(html.Div(f"{fm.get('uncoded_pct')}% of failures are uncoded (cannot be analysed).", style=MUTED))
    if result.get("reliability_interpretation"):
        kids.append(html.Div(result["reliability_interpretation"], style={**MUTED, "marginTop": "8px", "fontStyle": "italic"}))
    return _card("Reliability", html.Div(kids))


def _drift_anomaly(result: Dict[str, Any], live: bool = True):
    """SAP-transactional anomaly / drift artifact (tools 29-30): the flagged failure-interval drift + trend,
    reactive-work-mix trend, cohort bad-actor outlier, and the material/services maintenance-cost bands.
    Evidence-only - it flags a CANDIDATE change and names its type, but never changes the label or gate."""
    drift = result.get("reliability_drift") or {}
    cost = result.get("cost_distribution") or {}
    signals = [s for s in (drift.get("signals") or []) if s.get("computable")]
    if not signals and not cost.get("computable"):
        return None
    _STAT_KEYS = ("z_score", "slope_days_per_failure", "reactive_share", "cohort_z", "percentile_rank")
    kids = [html.Div("Anomaly / drift (evidence - flags a candidate change; does not change the label or gate)",
                     style=H2)]
    if signals:
        rows = []
        for s in signals:
            stat = s.get("statistic") or {}
            shown = "; ".join(f"{k}={stat[k]}" for k in _STAT_KEYS if k in stat) or "-"
            rows.append([s["signal"], s.get("direction") or "-", shown,
                         s.get("candidate_recommendation_type") or "-"])
        kids.append(_table(["Signal", "Direction", "Statistic", "Candidate type"], rows))
        flagged = drift.get("flagged_signals") or []
        if flagged:
            kids.append(html.Div("Flagged: " + ", ".join(flagged),
                                 style={"fontWeight": 700, "fontSize": "12px", "color": COLORS["oxy"], "marginTop": "6px"}))
    if cost.get("computable"):
        kids.append(html.Div("Maintenance-cost bands (material/services only - no labor / savings claim)",
                             style={**H2, "marginTop": "8px"}))
        kids.append(_table(["Cost band", "Value"], [
            ["P10", f"${cost.get('cost_p10'):,.0f}"], ["P50", f"${cost.get('cost_p50'):,.0f}"],
            ["P90", f"${cost.get('cost_p90'):,.0f}"],
            ["Cohort cost outlier", "yes" if cost.get("cohort_cost_outlier") else "no"]]))
    if drift.get("interpretation"):
        kids.append(html.Div(drift["interpretation"], style={**MUTED, "marginTop": "8px", "fontStyle": "italic"}))
    return _card("Anomaly / drift", html.Div(kids))


def _cost(result: Dict[str, Any], live: bool = True):
    d = result.get("evidence_digest") or {}
    labor, material = d.get("labor_cost"), d.get("material_cost")
    return _card("Cost view (baseline only)", html.Div([
        html.Div(f"Basis: {d.get('cost_basis') or '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div(f"Material cost: {material if material is not None else '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div(f"Labor cost: {labor if labor is not None else '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div("No labor-savings claim is defensible when labor cost is 0 (F1).", style=MUTED),
    ]))


def _pct(frac: Any) -> str:
    if frac is None:
        return "-"
    try:
        return f"{round(float(frac) * 100)}%"
    except (TypeError, ValueError):
        return str(frac)


def _wants_detail(result: Dict[str, Any]) -> bool:
    """Does the question ask for individual records? If so the Detailed tab opens by default."""
    q = (result.get("user_question") or "").lower()
    return any(k in q for k in ("detail", "all work order", "list", "record", "each order", "line item", "individual"))


def _wo_summary(result: Dict[str, Any]):
    """Summary view: the work-order breakdown (with shares) + the failure-coding table (the mix)."""
    ev = result.get("evidence") or {}
    wo = ev.get("work_order_history") or []
    findings = (ev.get("notification_findings") or [{}])[0]
    total = sum(int(r.get("n") or 0) for r in wo)

    def _share(n: Any) -> str:
        return f"{round(100 * int(n or 0) / total)}%" if total else "-"

    wo_rows = [[str(r.get("order_type", "")).title(), str(r.get("n", "")), _share(r.get("n"))] for r in wo]
    if wo_rows:
        wo_rows.append(["Total", str(total), "100%"])
    coding_rows = [
        ["Damage code present", _pct(findings.get("damage_coded_pct"))],
        ["Cause code present", _pct(findings.get("cause_coded_pct"))],
    ]
    return html.Div([
        html.Div("Work-order breakdown (scoped)", style=H2),
        _table(["Order type", "Count", "Share of total"], wo_rows) if wo_rows else html.Div("-", style=MUTED),
        html.Div("Aggregated counts by type - the mix, not individual line items. Switch to 'Detailed "
                 "records' for the per-order and per-notification rows.", style={**MUTED, "marginBottom": "14px"}),
        html.Div("Failure coding (scoped)", style=H2),
        _table(["Coding", "Share of notifications"], coding_rows),
        html.Div("Incomplete coding limits root-cause and interval analysis.", style=MUTED),
    ])


def _evidence_table(result: Dict[str, Any], live: bool = True):
    """Work-order evidence with a Summary <-> Detailed view toggle inside one artifact (the user's
    'summary/detailed view within artifacts'). Summary = breakdown + failure coding (the mix); Detailed
    = the individual work-order + notification records (Level 2), filterable + downloadable when live.
    Default view follows the question - a detail/list request opens Detailed. Only the newest answer is
    `live`; prior answers in the history render Detailed as static snapshots (no interactive ids)."""
    tab = {"padding": "6px 16px", "fontSize": "13px", "border": "none"}
    sel = {**tab, "fontWeight": 700, "color": COLORS["oxy"], "borderBottom": f"2px solid {COLORS['oxy']}"}
    tabs = dcc.Tabs(value=("detailed" if _wants_detail(result) else "summary"), children=[
        dcc.Tab(label="Summary", value="summary", style=tab, selected_style=sel,
                children=html.Div(_wo_summary(result), style={"paddingTop": "12px"})),
        dcc.Tab(label="Detailed records", value="detailed", style=tab, selected_style=sel,
                children=html.Div([_work_order_detail(result, live), _notification_detail(result, live)],
                                  style={"paddingTop": "12px", "display": "flex", "flexDirection": "column", "gap": "16px"})),
    ])
    return html.Div([html.Div("Work-order evidence", style={**H2, "marginBottom": "8px"}), tabs], style=CARD)


# --- Row-level detail tables (Level 2), Finance-app style: scrollable, sticky header, zebra rows ----
def _fmt_cell(v: Any) -> str:
    if v is None or v == "":
        return "-"                       # honest blank (e.g. absent labor actuals / uncoded notification)
    if isinstance(v, bool):
        return "Yes" if v else "-"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
    return str(v)


_DETAIL_TD = {"padding": "6px 12px", "fontSize": "12.5px", "color": COLORS["ink"],
              "borderBottom": f"1px solid {COLORS['line']}", "whiteSpace": "nowrap"}


def _build_detail_body(rows: List[Dict[str, Any]], columns: List[str]) -> list:
    """Render the <tr> rows. Shared by the initial render and the column-filter callback so both
    produce the same DOM shape (the callback replaces only the tbody, keeping the filter inputs)."""
    body = []
    for i, r in enumerate(rows):
        bg = "#fbfdff" if i % 2 else "white"
        body.append(html.Tr([html.Td(_fmt_cell(r.get(c)), style=_DETAIL_TD) for c in columns],
                            style={"background": bg}))
    return body


def _filter_rows(rows: List[Dict[str, Any]], filters: Dict[str, str]) -> List[Dict[str, Any]]:
    """Case-insensitive substring match, one needle per column, AND across columns (Finance-style)."""
    out = rows
    for col, needle in (filters or {}).items():
        nd = str(needle).strip().lower()
        if nd:
            out = [r for r in out if nd in _fmt_cell(r.get(col)).lower()]
    return out


def _detail_csv(columns: List[str], labels: Dict[str, str], rows: List[Dict[str, Any]]) -> str:
    """CSV of the (already filtered) rows, using the human column labels as the header."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([labels.get(c, c) for c in columns])
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in columns])
    return buf.getvalue()


def _detail_table(art_id: str, title: str, columns: List[str], labels: Dict[str, str],
                  rows: List[Dict[str, Any]], note: str = None, cap: int = 50, live: bool = True):
    """Finance-style detail table: scrollable + sticky header, zebra rows. When `live` it adds the
    per-column filter row, the 'N of M' status, a CSV download, and a data store (wired by the MATCH
    callbacks in app.py, keyed on `art_id`). Prior-answer (non-live) copies render as static snapshots
    with NO interactive ids, so the fixed ids never duplicate across the artifacts history."""
    title_el = html.Div(title, style={**H2, "marginBottom": "6px"})
    if not rows:
        return html.Div([title_el, html.Div("No scoped records (or the asset is out of analysis scope).", style=MUTED)])
    shown = rows[:cap]
    th = {"padding": "8px 12px", "textAlign": "left", "fontSize": "12px", "fontWeight": 700,
          "color": COLORS["muted"], "borderBottom": f"2px solid {COLORS['line']}", "background": "#fbfdff",
          "position": "sticky", "top": "0", "zIndex": "2", "whiteSpace": "nowrap"}
    thead_rows = [html.Tr([html.Th(labels.get(c, c), style=th) for c in columns])]
    tbody_kwargs = {}
    if live:
        th_filter = {"padding": "4px 8px", "background": "#fbfdff", "borderBottom": f"1px solid {COLORS['line']}",
                     "position": "sticky", "top": "31px", "zIndex": "1"}
        thead_rows.append(html.Tr([html.Th(dcc.Input(
            id={"type": "detail-filter", "art": art_id, "col": c}, type="text", value="", debounce=True,
            placeholder="filter", style={"width": "100%", "boxSizing": "border-box", "fontSize": "11px",
                                          "padding": "3px 6px", "border": f"1px solid {COLORS['line']}", "borderRadius": "5px"}),
            style=th_filter) for c in columns]))
        tbody_kwargs = {"id": {"type": "detail-body", "art": art_id}}
    table = html.Div(
        html.Table([html.Thead(thead_rows), html.Tbody(_build_detail_body(shown, columns), **tbody_kwargs)],
                   style={"width": "100%", "borderCollapse": "collapse"}),
        style={"overflowX": "auto", "overflowY": "auto", "maxHeight": "420px",
               "border": f"1px solid {COLORS['line']}", "borderRadius": "8px"},
    )
    cap_note = f" - showing first {cap} of {len(rows)}" if len(rows) > cap else ""
    if live:
        controls = html.Div([
            html.Div(f"{len(shown)} record(s){cap_note}", id={"type": "detail-status", "art": art_id}, style={**MUTED}),
            html.Button("Download CSV", id={"type": "detail-download-btn", "art": art_id}, n_clicks=0,
                        style={"border": f"1px solid {COLORS['line']}", "background": "white", "borderRadius": "6px",
                               "padding": "4px 10px", "fontSize": "12px", "cursor": "pointer",
                               "color": COLORS["oxy"], "fontWeight": 700}),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"})
        extras = [dcc.Store(id={"type": "detail-store", "art": art_id}, data={"rows": rows, "columns": columns, "labels": labels}),
                  dcc.Download(id={"type": "detail-download", "art": art_id})]
    else:
        controls = html.Div(f"{len(shown)} record(s){cap_note} (snapshot)", style={**MUTED, "marginBottom": "6px"})
        extras = []
    kids = [title_el, controls, table] + extras
    if note:
        kids.append(html.Div(note, style={**MUTED, "marginTop": "6px"}))
    return html.Div(kids)


_WO_DETAIL_COLS = ["wo_number", "order_date", "order_type", "activity_type", "description", "planned_hours",
                   "actual_labor_hours", "material_cost", "labor_cost", "work_center", "status"]
_WO_DETAIL_LABELS = {"wo_number": "WO #", "order_date": "Date", "order_type": "Type", "activity_type": "Activity",
                     "description": "Description", "planned_hours": "Planned hrs", "actual_labor_hours": "Actual labor hrs",
                     "material_cost": "Material cost", "labor_cost": "Labor cost", "work_center": "Work ctr", "status": "Status"}
_NOTIF_DETAIL_COLS = ["notification_number", "failure_date", "damage_code", "cause_code", "object_part",
                      "breakdown_duration_hrs", "linked_wo"]
_NOTIF_DETAIL_LABELS = {"notification_number": "Notif #", "failure_date": "Failure date", "damage_code": "Damage code",
                        "cause_code": "Cause code", "object_part": "Object part", "breakdown_duration_hrs": "Breakdown hrs",
                        "linked_wo": "Linked WO"}


def _work_order_detail(result: Dict[str, Any], live: bool = True):
    rows = (result.get("evidence") or {}).get("work_order_detail") or []
    return _detail_table("work_order_detail", "Work orders - individual records (scoped)",
                         _WO_DETAIL_COLS, _WO_DETAIL_LABELS, rows, live=live,
                         note="Actual labor hrs and Labor cost are blank because SOAR posts no labor actuals - "
                              "the empty column IS the evidence gap, not a rendering error.")


def _notification_detail(result: Dict[str, Any], live: bool = True):
    rows = (result.get("evidence") or {}).get("notification_detail") or []
    return _detail_table("notification_detail", "Notifications - individual failure records (scoped)",
                         _NOTIF_DETAIL_COLS, _NOTIF_DETAIL_LABELS, rows, live=live,
                         note="Blank damage / cause codes are the coding gap that drives the 'Governance Review "
                              "Required' label - each blank row is a notification a reviewer cannot yet analyse.")


# Every renderer takes (result, live). The detail views inside evidence_table use `live` for their
# interactive ids; the standalone visuals ignore it. The deterministic tool trace + scoped SQL are NOT
# artifacts - they live in the dedicated Governance Trace tab (render_governance_trace).
_RENDERERS = {
    "work_order_mix": _work_order_mix,
    "data_readiness": _data_readiness,
    "cost": _cost,
    "comparison": lambda r, live=True: render_comparison(r),
    "evidence_table": _evidence_table,
    "reliability": _reliability,
    "drift_anomaly": _drift_anomaly,
}
assert set(_RENDERERS) == set(ARTIFACT_CHOICES)  # catalog and renderers stay in lockstep


def default_artifacts(result: Dict[str, Any]) -> List[str]:
    """Fail-closed floor: a sensible default set when the model selected nothing valid."""
    rt = (result.get("review_type") or "").lower()
    base = (["work_order_mix", "comparison"]
            if any(k in rt for k in ("frequency", "cbm", "retire", "run-to-failure"))
            else ["work_order_mix", "evidence_table"])
    # Surface the anomaly/drift card whenever a SAP drift signal actually fired, even if unselected.
    if (result.get("reliability_drift") or {}).get("any_drift_flag"):
        base.append("drift_anomaly")
    return base


def render_artifacts(result: Dict[str, Any], selected: Optional[List[str]] = None, live: bool = True) -> html.Div:
    """Render the model-selected artifacts (validated), stacked; fall back to the deterministic set.
    `live=False` renders a static snapshot (no interactive ids) for prior answers in the history."""
    names = [n for n in (selected or []) if n in _RENDERERS] or default_artifacts(result)
    cards = []
    for n in names:
        try:
            c = _RENDERERS[n](result, live)
        except Exception:
            c = None
        if c is not None:
            cards.append(c)
    if not cards:
        cards = [html.Div("No visual artifacts apply to this question.", style=MUTED)]
    return html.Div(cards, style={"display": "flex", "flexDirection": "column", "gap": "12px"})


def empty_state(icon_src: str, text: str) -> html.Div:
    """Shared right-panel empty state: one large centered icon + a short contextual line below it.
    The container is a flex column that vertically centers its content over the panel height; when a
    tab has content instead, the normal top-aligned card flow renders (this element is not used)."""
    return html.Div([
        html.Img(src=icon_src, style={"width": "52px", "height": "52px", "marginBottom": "16px"}),
        html.Div(text, style={"fontSize": "13px", "color": COLORS["muted"], "maxWidth": "300px",
                              "textAlign": "center", "lineHeight": "1.5"}),
    ], style={"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center",
              "textAlign": "center", "minHeight": "calc(100vh - 210px)", "padding": "24px", "boxSizing": "border-box"})


def artifacts_empty() -> html.Div:
    return empty_state("/assets/icons/artifacts.svg",
                       "Ask MAX a question - each answer's artifacts appear here, newest first.")


def preview_empty() -> html.Div:
    return empty_state("/assets/icons/preview.svg",
                       "Ask about a specific PM - its decision preview appears here.")


def trace_empty() -> html.Div:
    return empty_state("/assets/icons/trace.svg",
                       "Ask MAX a question - the governance trace for each answer appears here.")


def _history_cards(history: List[Dict[str, Any]], collapsed: Optional[List[int]],
                   hdr_type: str, body_fn, empty_el: html.Div) -> html.Div:
    """Shared Finance-style history stack: one collapsible card per answered question, newest first,
    labelled by its question + timestamp (the newest tagged 'newest'). `hdr_type` names the header's
    pattern id (so Artifacts and Governance-Trace stacks toggle independently); `body_fn(entry, is_newest)`
    renders that card's body. Collapsed cards render header-only. `empty_el` is the centered empty
    state shown when there is no history yet."""
    if not history:
        return empty_el
    collapsed_set = set(collapsed or [])
    newest_n = max(e.get("n", 0) for e in history)
    cards = []
    for e in sorted(history, key=lambda x: x.get("n", 0), reverse=True):
        n = e.get("n")
        is_open = n not in collapsed_set
        header = html.Button(
            [
                html.Span("▾" if is_open else "▸",
                          style={"marginRight": "8px", "color": COLORS["muted"], "fontSize": "12px"}),
                html.Span(e.get("question") or "Query",
                          style={"fontWeight": 700, "color": COLORS["ink"], "fontSize": "13px", "flex": "1",
                                 "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap", "textAlign": "left"}),
                html.Span(("newest" if n == newest_n else e.get("ts", "")),
                          style={"fontSize": "11px", "color": COLORS["oxy"] if n == newest_n else COLORS["muted"], "marginLeft": "10px"}),
            ],
            id={"type": hdr_type, "n": n}, n_clicks=0,
            style={"display": "flex", "alignItems": "center", "width": "100%", "border": "none", "cursor": "pointer",
                   "background": "#fbfdff", "padding": "9px 12px",
                   "borderRadius": "8px 8px 0 0" if is_open else "8px",
                   "borderBottom": f"1px solid {COLORS['line']}" if is_open else "none"},
        )
        kids = [header]
        if is_open:
            kids.append(html.Div(body_fn(e, n == newest_n), style={"padding": "12px"}))
        cards.append(html.Div(kids, style={"border": f"1px solid {COLORS['line']}", "borderRadius": "8px",
                                           "background": "white", "overflow": "hidden"}))
    return html.Div(cards, style={"display": "flex", "flexDirection": "column", "gap": "10px"})


_FF_INTENT_LABEL = {"INFO": "Look-up / explanation", "GATE_CHECK": "Advisory gate check",
                    "APPROVAL": "Governed action"}


def render_free_flow_card(entry: Dict[str, Any]) -> html.Div:
    """The Artifacts-tab card for a FREE_FLOW answer: MAX's answer (summary) + the DETAIL it is grounded
    in (the last governed decision's gate / recommendation / evidence). Read-only - a free-flow turn never
    mints a governed decision, so this card carries no interactive ids and no change package."""
    intent = entry.get("intent", "INFO")
    ref = entry.get("ref") or {}
    kids: List[Any] = [html.Div(f"Ask MAX - {_FF_INTENT_LABEL.get(intent, 'Free-flow answer')}", style=H2)]
    if entry.get("answer"):
        kids.append(dcc.Markdown(entry["answer"], style={"fontSize": "13px", "lineHeight": "1.5",
                                                          "color": COLORS["ink"], "marginBottom": "10px"}))
    if ref.get("gate_status") or ref.get("recommendation_type") or ref.get("evidence_lines"):
        kids.append(html.Div("Grounded in the last governed decision", style={"fontSize": "12px",
                    "fontWeight": 700, "color": COLORS["muted"], "marginBottom": "4px"}))
        if ref.get("equipment_id"):
            kids.append(_kv("Asset", ref.get("equipment_id")))
        if ref.get("gate_status"):
            kids.append(html.Div([html.Span("Gate  ", style={"color": COLORS["muted"], "fontSize": "12px"}),
                        badge(gate_label(ref.get("gate_status")), STATUS_COLORS.get(ref.get("gate_status"), COLORS["muted"])),
                        html.Span(" " + (ref.get("gate_reason") or ""), style={"color": COLORS["muted"],
                                  "fontSize": "12px", "marginLeft": "6px"})], style={"margin": "3px 0"}))
        if ref.get("recommendation_type"):
            kids.append(_kv("Recommendation", rec_label(ref.get("recommendation_type"))))
        for line in (ref.get("evidence_lines") or [])[:6]:
            kids.append(html.Div("- " + str(line), style={"fontSize": "13px", "color": COLORS["ink"], "margin": "2px 0"}))
    if intent == "GATE_CHECK":
        kids.append(html.Div("Advisory preview - NOT the authoritative decision. It drafts nothing; run a "
                             "governed review to make any change official.",
                             style={"background": "#eef4ff", "border": "1px solid #cfe0ff", "borderRadius": "8px",
                                    "padding": "8px", "fontSize": "12px", "color": "#2a4a7a", "marginTop": "8px"}))
    elif intent == "APPROVAL":
        kids.append(html.Div("Approve / reject buttons are in the chat; the authenticated human commits via the "
                             "governed workflow (role + gate + self-approval + audit). Draft-only; MAX never writes SAP.",
                             style={"background": "#fff4e5", "border": "1px solid #f0c987", "borderRadius": "8px",
                                    "padding": "8px", "fontSize": "12px", "color": "#8a5a00", "marginTop": "8px"}))
    return html.Div(kids, style=CARD)


def render_free_flow_trace_note(entry: Dict[str, Any]) -> html.Div:
    """Governance-Trace card for a free-flow turn: it ran no governed pipeline (a gate-check is a read-only
    ADVISORY preview; an approval is a human-committed action recorded to the session audit trail)."""
    intent = entry.get("intent", "INFO")
    note = {
        "GATE_CHECK": "Advisory gate check: a READ-ONLY preview of the deterministic gate on a hypothetical "
                      "change. No governed decision was made and nothing was drafted.",
        "APPROVAL": "Governed action: the human clicked an approve/reject button; the outcome was decided by "
                    "approval_workflow_state (role + gate + self-approval) and recorded to the session audit trail.",
    }.get(intent, "Free-flow answer: read-only explanation from the last governed result. No governed pipeline ran.")
    return html.Div([html.Div("No governed pipeline (free-flow)", style=H2),
                     html.Div(note, style={"fontSize": "13px", "color": COLORS["ink"], "lineHeight": "1.5"})], style=CARD)


def render_artifact_history(history: List[Dict[str, Any]], collapsed: Optional[List[int]] = None) -> html.Div:
    """Artifacts tab as a history stack. Governed answers render their artifact set (only the newest is
    `live` with interactive filters/download/toggle); FREE_FLOW answers render a read-only free-flow card."""
    def body(e, newest):
        if e.get("kind") == "free_flow":
            return render_free_flow_card(e)
        return render_artifacts(e.get("result") or {}, e.get("selected"), live=newest)
    return _history_cards(history, collapsed, "arti-hdr", body, artifacts_empty())


def render_trace_history(history: List[Dict[str, Any]], collapsed: Optional[List[int]] = None) -> html.Div:
    """Governance Trace tab as a history stack: every governed answer's FULL governance trace (model tool
    plan + deterministic tool trace + scoped SQL); a FREE_FLOW answer shows a short read-only note."""
    def body(e, newest):
        if e.get("kind") == "free_flow":
            return render_free_flow_trace_note(e)
        return render_governance_trace(e.get("result") or {})
    return _history_cards(history, collapsed, "trace-hdr", body, trace_empty())
