"""Command Center: queue-first PM triage landing (per 50 - UI and Experience).

Layout: a left 'Review Priorities' filter rail (clickable tiles that filter the queue) + a center
PM Health queue (per-column filters under the headers) + a right conditional PM-Preview slide-over.

Interactions (wired in app.py):
- Priority tile click  -> filters the queue (sets the table filter_query).
- Row body / chevron   -> opens the PM-Preview slide-over (stays in Command Center).
- Asset / PM name click -> opens Work Strategy Studio directly for that PM.

All values are governed: the queue comes from portfolio_health(); the preview from agent.run(asset).
"""

from __future__ import annotations

from typing import Any, Dict, List

from dash import dash_table, dcc, html

from .theme import COLORS, MUTED, RAG_COLORS, STATUS_COLORS

# Priority tiles: key -> (label, description, accent colour, table filter_query).
PRIORITY_KEYS = ["blocked", "review", "draft", "missing", "readiness"]
_PRIORITY = {
    "blocked": ("Blocked", "Require immediate attention", STATUS_COLORS.get("BLOCKED", "#c1261b")),
    "review": ("Review Required", "Human review needed", STATUS_COLORS.get("REVIEW_REQUIRED", "#f2a000")),
    "draft": ("Draft Only", "Draft package available", STATUS_COLORS.get("DRAFT_ONLY", "#0b5cab")),
    "missing": ("Missing Evidence", "Evidence required", "#6f42c1"),
    "readiness": ("Data Readiness", "Fleet average readiness", "#15803d"),
}
FILTER_BY_PRIORITY = {
    "blocked": '{gate_status} = "BLOCKED"',
    "review": '{gate_status} = "REVIEW_REQUIRED"',
    "draft": '{gate_status} = "DRAFT_ONLY"',
    "missing": '{label} contains "Missing Evidence"',
    "readiness": '{data_readiness} != "GREEN"',
}


def priority_tile_style(active: bool, color: str) -> dict:
    return {
        "display": "block", "width": "100%", "textAlign": "left", "cursor": "pointer",
        "background": "white", "borderRadius": "12px", "padding": "14px 16px", "marginBottom": "10px",
        "borderLeft": f"4px solid {color}",
        "border": f"1px solid {color if active else COLORS['line']}",
        "boxShadow": f"0 0 0 2px {color}22" if active else "none",
    }


def _priority_counts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows) or 1
    green = sum(1 for r in rows if r.get("data_readiness") == "GREEN")
    return {
        "blocked": sum(1 for r in rows if r.get("gate_status") == "BLOCKED"),
        "review": sum(1 for r in rows if r.get("gate_status") == "REVIEW_REQUIRED"),
        "draft": sum(1 for r in rows if r.get("gate_status") == "DRAFT_ONLY"),
        "missing": sum(1 for r in rows if (r.get("label") or "").startswith("Missing Evidence")),
        "readiness": f"{round(100 * green / n)}%",
    }


def priority_tile(key: str, value: Any) -> html.Button:
    label, desc, color = _PRIORITY[key]
    return html.Button([
        html.Div(str(value), style={"fontSize": "26px", "fontWeight": 800, "color": color}),
        html.Div(label, style={"fontSize": "14px", "fontWeight": 700, "color": COLORS["ink"]}),
        html.Div(desc, style={"fontSize": "11px", "color": COLORS["muted"]}),
    ], id=f"cc-prio-{key}", n_clicks=0, style=priority_tile_style(False, color))


def _priorities_rail(rows: List[Dict[str, Any]]) -> html.Div:
    counts = _priority_counts(rows)
    return html.Div([
        html.Div("Review Priorities", style={"fontSize": "16px", "fontWeight": 800, "color": COLORS["ink"]}),
        html.Div("Click a priority to filter the queue.", style={**MUTED, "marginBottom": "14px"}),
        *[priority_tile(k, counts[k]) for k in PRIORITY_KEYS],
    ], style={"width": "260px", "flex": "0 0 260px", "paddingRight": "18px"})


def _queue_table(rows: List[Dict[str, Any]]) -> dash_table.DataTable:
    data = [{
        "rank": i + 1, "equipment_id": r.get("equipment_id"), "pm_id": r.get("pm_id"),
        "label": r.get("label"), "gate_status": r.get("gate_status"),
        "next_action": r.get("next_action") or "-", "reason": r.get("gate_reason") or "-",
        "data_readiness": r.get("data_readiness"), "chevron": ">",
    } for i, r in enumerate(rows)]

    style_cond = [
        # blue, clickable-looking asset / PM name -> opens Studio
        {"if": {"column_id": "equipment_id"}, "color": COLORS["oxy"], "fontWeight": 700},
        {"if": {"column_id": "pm_id"}, "color": COLORS["oxy"]},
        {"if": {"column_id": "chevron"}, "color": COLORS["muted"], "textAlign": "center"},
    ]
    for status, color in STATUS_COLORS.items():
        style_cond.append({"if": {"filter_query": f'{{gate_status}} = "{status}"', "column_id": "gate_status"},
                           "backgroundColor": color, "color": "white", "fontWeight": 700, "textAlign": "center"})

    return dash_table.DataTable(
        id="pmhealth-table",
        columns=[
            {"name": "#", "id": "rank"}, {"name": "Asset", "id": "equipment_id"},
            {"name": "PM", "id": "pm_id"}, {"name": "Label", "id": "label"},
            {"name": "Gate", "id": "gate_status"}, {"name": "Recommended Next Action", "id": "next_action"},
            {"name": "Reason", "id": "reason"}, {"name": "", "id": "chevron"},
        ],
        data=data,
        hidden_columns=["data_readiness"],
        filter_action="native", sort_action="native", page_size=15, cell_selectable=True,
        style_as_list_view=True,
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell={"fontFamily": "inherit", "fontSize": "12px", "padding": "9px 10px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto", "border": "none",
                    "borderBottom": f"1px solid {COLORS['line']}"},
        style_header={"fontWeight": 700, "color": COLORS["muted"], "backgroundColor": "#f7f9fc",
                      "border": "none", "borderBottom": f"2px solid {COLORS['line']}", "textTransform": "none"},
        style_filter={"backgroundColor": "#fbfdff", "border": "none", "borderBottom": f"1px solid {COLORS['line']}"},
        style_data_conditional=style_cond,
        css=[{"selector": ".show-hide", "rule": "display: none"}],
    )


def render_command_center(portfolio_health: Dict[str, Any]) -> html.Div:
    rows = (portfolio_health or {}).get("rows", [])
    queue = html.Div([
        html.Div([
            html.Div([
                html.Span("PM Health Review Queue ", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"]}),
                html.Span("(highest attention first)", style={"fontSize": "13px", "color": COLORS["muted"]}),
            ]),
            html.Div(f"{len(rows)} items", style={"fontSize": "13px", "color": COLORS["muted"]}),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "baseline", "marginBottom": "4px"}),
        html.Div("Select a row to open PM preview. Click the asset or PM name to open Work Strategy Studio.",
                 style={**MUTED, "marginBottom": "12px"}),
        _queue_table(rows),
    ], style={"flex": "1", "minWidth": "0", "background": "white", "border": f"1px solid {COLORS['line']}",
              "borderRadius": "12px", "padding": "16px 18px"})

    return html.Div([
        html.Div("Command Center", style={"fontSize": "18px", "fontWeight": 800, "color": COLORS["ink"], "marginBottom": "2px"}),
        html.Div("Fleet PM triage - highest-attention PMs first.", style={**MUTED, "marginBottom": "14px"}),
        html.Div([
            _priorities_rail(rows),
            queue,
            html.Div(id="cc-preview", style={"flex": "0 0 auto"}),  # PM preview slide-over (fills on row select)
        ], style={"display": "flex", "alignItems": "flex-start", "gap": "16px"}),
    ], style={"padding": "18px 22px"})


# --- PM Preview slide-over --------------------------------------------------
def _line(label: str, value: Any) -> html.Div:
    return html.Div([
        html.Span(label, style={"color": COLORS["muted"], "fontSize": "12px", "display": "inline-block", "minWidth": "110px"}),
        html.Span(str(value if value is not None else "-"), style={"color": COLORS["ink"], "fontSize": "13px", "fontWeight": 600}),
    ], style={"margin": "6px 0"})


def _pill(text: str, color: str) -> html.Span:
    return html.Span(text or "-", style={"display": "inline-block", "padding": "3px 10px", "borderRadius": "999px",
                                          "background": color, "color": "white", "fontSize": "11px", "fontWeight": 700})


def render_pm_preview(result: Dict[str, Any]) -> html.Div:
    if not result or result.get("error"):
        return html.Div()
    eid = result.get("equipment_id")
    gate = result.get("gate_status")
    label = result.get("classifier_label")
    reason = result.get("gate_reason") or result.get("gate_review_trigger") or "-"
    rationale = result.get("recommendation_rationale") or "-"
    current_pm = (result.get("proposed_summary") or "").split(" -> ")[0] or "-"
    allowed = result.get("allowed_next_actions") or []
    blocked = result.get("blocked_actions") or []
    gate_color = STATUS_COLORS.get(gate, COLORS["muted"])
    protected = result.get("do_not_optimize") or label == "Governance Review Required"
    oxy_ctx = ("Criticality / mandatory-protected PM; human review required; MAX cannot write SAP."
               if protected else "Draft-only in Wave 1; humans approve; MAX cannot write SAP.")

    return html.Div([
        html.Div([
            html.Div(f"{eid}  PM Review Preview", style={"fontSize": "15px", "fontWeight": 800, "color": COLORS["ink"]}),
            html.Button("x", id="cc-preview-close", n_clicks=0,
                        style={"border": "none", "background": "transparent", "cursor": "pointer",
                               "fontSize": "18px", "color": COLORS["muted"]}),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"}),

        html.Div([html.Span(eid, style={"fontSize": "17px", "fontWeight": 800, "color": COLORS["oxy"], "marginRight": "10px"}),
                  _pill(gate, gate_color)], style={"marginBottom": "10px"}),

        _line("Asset Type", result.get("asset_class")),
        _line("Criticality", f"{result.get('criticality_code')} {result.get('criticality_label') or ''}".strip()),
        _line("Current PM", current_pm),
        _line("Classification", label),
        html.Hr(style={"border": "none", "borderTop": f"1px solid {COLORS['line']}", "margin": "10px 0"}),
        html.Div([html.Span("Gate  ", style={"color": COLORS["muted"], "fontSize": "12px"}), _pill(gate, gate_color)]),
        _line("Reason", reason),

        html.Div("Plain-language reason", style={"fontWeight": 700, "fontSize": "12px", "marginTop": "10px"}),
        html.Div(rationale, style={"fontSize": "13px", "color": COLORS["ink"], "margin": "3px 0"}),
        html.Div("Oxy context", style={"fontWeight": 700, "fontSize": "12px", "marginTop": "10px", "color": COLORS["oxy"]}),
        html.Div(oxy_ctx, style={"fontSize": "13px", "color": COLORS["ink"], "margin": "3px 0"}),

        html.Div("Allowed next action", style={"fontWeight": 700, "fontSize": "12px", "marginTop": "10px", "color": "#15803d"}),
        html.Div(", ".join(allowed) if allowed else (result.get("recommendation_next_action") or "-"),
                 style={"fontSize": "13px", "color": COLORS["ink"], "margin": "3px 0"}),
        html.Div("Blocked action", style={"fontWeight": 700, "fontSize": "12px", "marginTop": "10px", "color": "#c1261b"}),
        html.Div(", ".join(blocked) if blocked else "Direct SAP update / unattended reduction",
                 style={"fontSize": "13px", "color": COLORS["ink"], "margin": "3px 0"}),

        html.Button("Ask MAX about this PM", id="cc-ask-btn", n_clicks=0,
                    style={"width": "100%", "marginTop": "16px", "padding": "11px", "border": "none",
                           "borderRadius": "10px", "background": COLORS["oxy"], "color": "white",
                           "fontWeight": 700, "cursor": "pointer"}),
        html.Button("Open in Studio", id="cc-studio-btn", n_clicks=0,
                    style={"width": "100%", "marginTop": "8px", "padding": "11px", "cursor": "pointer",
                           "border": f"1px solid {COLORS['oxy']}", "borderRadius": "10px",
                           "background": "white", "color": COLORS["oxy"], "fontWeight": 700}),
    ], style={"flex": "0 0 340px", "width": "340px", "background": "white", "border": f"1px solid {COLORS['line']}",
              "borderRadius": "12px", "padding": "16px 18px", "boxShadow": "0 2px 12px rgba(11,36,49,0.08)"})
