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
from .artifacts import _table, render_comparison, render_tool_trace
from .theme import CARD, COLORS, H2, MUTED, RAG_COLORS


def _card(title: str, body: Any) -> html.Div:
    return html.Div([html.Div(title, style=H2), body], style=CARD)


def _work_order_mix(result: Dict[str, Any]):
    by_type = (result.get("evidence_digest") or {}).get("work_orders_by_type") or {}
    if not by_type:
        return None
    keys = list(by_type)
    fig = go.Figure(go.Bar(x=keys, y=[by_type[k] for k in keys], marker_color=COLORS["oxy"]))
    fig.update_layout(title="Work-order mix (scoped)", height=260, margin=dict(l=30, r=20, t=40, b=30),
                      paper_bgcolor="white", plot_bgcolor="white", yaxis_title="orders")
    return html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False})], style=CARD)


def _data_readiness(result: Dict[str, Any]):
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


def _cost(result: Dict[str, Any]):
    d = result.get("evidence_digest") or {}
    labor, material = d.get("labor_cost"), d.get("material_cost")
    return _card("Cost view (baseline only)", html.Div([
        html.Div(f"Basis: {d.get('cost_basis') or '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div(f"Material cost: {material if material is not None else '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div(f"Labor cost: {labor if labor is not None else '-'}", style={"fontSize": "13px", "margin": "3px 0"}),
        html.Div("No labor-savings claim is defensible when labor cost is 0 (F1).", style=MUTED),
    ]))


def _evidence_table(result: Dict[str, Any]):
    ev = result.get("evidence") or {}
    wo = ev.get("work_order_history") or []
    findings = (ev.get("notification_findings") or [{}])[0]
    rows = [[str(r.get("order_type", "")), str(r.get("n", ""))] for r in wo]
    return _card("Scoped evidence records", html.Div([
        _table(["Work-order type", "Count"], rows) if rows else html.Div("-", style=MUTED),
        html.Div(f"Failure coding - damage: {findings.get('damage_coded_pct')}, cause: {findings.get('cause_coded_pct')}",
                 style={**MUTED, "marginTop": "6px"}),
    ]))


_RENDERERS = {
    "work_order_mix": _work_order_mix,
    "data_readiness": _data_readiness,
    "cost": _cost,
    "comparison": render_comparison,
    "evidence_table": _evidence_table,
    "gate_trace": render_tool_trace,
}
assert set(_RENDERERS) == set(ARTIFACT_CHOICES)  # catalog and renderers stay in lockstep


def default_artifacts(result: Dict[str, Any]) -> List[str]:
    """Fail-closed floor: a sensible default set when the model selected nothing valid."""
    rt = (result.get("review_type") or "").lower()
    if any(k in rt for k in ("frequency", "cbm", "retire", "run-to-failure")):
        return ["work_order_mix", "comparison", "gate_trace"]
    return ["work_order_mix", "evidence_table", "gate_trace"]


def render_artifacts(result: Dict[str, Any], selected: Optional[List[str]] = None) -> html.Div:
    """Render the model-selected artifacts (validated), stacked; fall back to the deterministic set."""
    names = [n for n in (selected or []) if n in _RENDERERS] or default_artifacts(result)
    cards = []
    for n in names:
        try:
            c = _RENDERERS[n](result)
        except Exception:
            c = None
        if c is not None:
            cards.append(c)
    if not cards:
        cards = [html.Div("No visual artifacts apply to this question.", style=MUTED)]
    return html.Div(cards, style={"display": "flex", "flexDirection": "column", "gap": "12px"})
