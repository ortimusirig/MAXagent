"""Command Center: queue-first PM triage landing (per 50 - UI and Experience).

Layout: a left 'Review Priorities' filter rail (clickable tiles) + a center PM Health queue (per-column
filters under the headers, case-insensitive) + a right conditional PM-Preview slide-over.

Interactions (wired in app.py):
- Priority tile click  -> filters the queue DATA (subset), native column filters run on top.
- Row body / chevron   -> opens the PM-Preview slide-over (stays in Command Center).
- Asset / PM name click -> opens Work Strategy Studio directly for that PM.

All values are governed: the queue comes from portfolio_health(); the preview from agent.run(asset).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import dash_table, dcc, html

from .artifacts import render_why
from .theme import COLORS, MUTED, STATUS_COLORS

# Priority tiles: key -> (label, description, accent colour).
PRIORITY_KEYS = ["blocked", "review", "draft", "missing", "readiness"]
_PRIORITY = {
    "blocked": ("Blocked", "Require immediate attention", STATUS_COLORS.get("BLOCKED", "#c1261b")),
    "review": ("Review Required", "Human review needed", STATUS_COLORS.get("REVIEW_REQUIRED", "#f2a000")),
    "draft": ("Draft Only", "Draft package available", STATUS_COLORS.get("DRAFT_ONLY", "#0b5cab")),
    "missing": ("Missing Evidence", "Evidence required", "#6f42c1"),
    "readiness": ("Data Readiness", "Fleet average readiness", "#15803d"),
}


def priority_match(d: Dict[str, Any], key: str) -> bool:
    """Does a queue row match a priority tile?"""
    gate = d.get("gate_status")
    if key == "blocked":
        return gate == "BLOCKED"
    if key == "review":
        return gate == "REVIEW_REQUIRED"
    if key == "draft":
        return gate == "DRAFT_ONLY"
    if key == "missing":
        return (d.get("label") or "").startswith("Missing Evidence")
    if key == "readiness":
        return d.get("data_readiness") != "GREEN"
    return True


def queue_data(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the table-row dicts from portfolio_health rows (governed)."""
    return [{
        "rank": i + 1, "equipment_id": r.get("equipment_id"), "pm_id": r.get("pm_id"),
        "label": r.get("label"), "gate_status": r.get("gate_status"),
        "next_action": r.get("next_action") or "-", "reason": r.get("gate_reason") or "-",
        "data_readiness": r.get("data_readiness"), "chevron": ">",
    } for i, r in enumerate(rows)]


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
    style_cond = [
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
        data=queue_data(rows),
        hidden_columns=["data_readiness"],
        filter_action="native", filter_options={"case": "insensitive"},
        sort_action="native", page_size=15, cell_selectable=True,
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
        dcc.Store(id="cc-all-rows", data=queue_data(rows)),  # full queue for server-side priority filtering
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


def render_pm_preview(result: Dict[str, Any], actions: bool = True, narrative: Optional[str] = None) -> html.Div:
    """PM preview. actions=True: the Command Center slide-over (close + Ask/Studio CTAs).
    actions=False: the read-only Ask MAX 'Preview' tab (no CTA ids, so no duplicate-id clash).
    `narrative` is MAX's assessment paragraph (LLM when bound); falls back to a deterministic one."""
    if not result or result.get("error"):
        return html.Div()
    eid = result.get("equipment_id")
    gate = result.get("gate_status")
    label = result.get("classifier_label")
    reason = result.get("gate_reason") or result.get("gate_review_trigger") or "-"
    current_pm = (result.get("proposed_summary") or "").split(" -> ")[0] or "-"
    gate_color = STATUS_COLORS.get(gate, COLORS["muted"])
    if narrative is None:
        from ..prompts import preview_summary
        narrative = preview_summary(result)

    header_kids = [html.Div(f"{eid}  PM Review Preview", style={"fontSize": "15px", "fontWeight": 800, "color": COLORS["ink"]})]
    if actions:
        header_kids.append(html.Button("x", id="cc-preview-close", n_clicks=0,
                                       style={"border": "none", "background": "transparent", "cursor": "pointer",
                                              "fontSize": "18px", "color": COLORS["muted"]}))

    children = [
        html.Div(header_kids, style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"}),
        html.Div([html.Span(eid, style={"fontSize": "17px", "fontWeight": 800, "color": COLORS["oxy"], "marginRight": "10px"}),
                  _pill(gate, gate_color)], style={"marginBottom": "10px"}),
        _line("Asset Type", result.get("asset_class")),
        _line("Criticality", f"{result.get('criticality_code')} {result.get('criticality_label') or ''}".strip()),
        _line("Current PM", current_pm),
        _line("Classification", label),
        _line("Reason", reason),
        html.Hr(style={"border": "none", "borderTop": f"1px solid {COLORS['line']}", "margin": "12px 0 6px"}),
        # The SAME governed synthesis block as the Studio's 'Why MAX recommended this' (narrative +
        # evidence cited + required approvers) so the Command Center preview reads identically to panel 3.
        render_why(result, narrative),
    ]
    if actions:
        children += [
            html.Button("Ask MAX about this PM", id="cc-ask-btn", n_clicks=0,
                        style={"width": "100%", "marginTop": "16px", "padding": "11px", "border": "none",
                               "borderRadius": "10px", "background": COLORS["oxy"], "color": "white",
                               "fontWeight": 700, "cursor": "pointer"}),
            html.Button("Open in Studio", id="cc-studio-btn", n_clicks=0,
                        style={"width": "100%", "marginTop": "8px", "padding": "11px", "cursor": "pointer",
                               "border": f"1px solid {COLORS['oxy']}", "borderRadius": "10px",
                               "background": "white", "color": COLORS["oxy"], "fontWeight": 700}),
        ]
    wrap = {"background": "white", "border": f"1px solid {COLORS['line']}", "borderRadius": "12px", "padding": "16px 18px"}
    if actions:
        wrap.update({"flex": "0 0 340px", "width": "340px", "boxShadow": "0 2px 12px rgba(11,36,49,0.08)"})
    return html.Div(children, style=wrap)
