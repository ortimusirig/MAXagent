"""Plotly figures for the PM Health portfolio view."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

import plotly.graph_objects as go

from .theme import STATUS_COLORS

_STATUS_ORDER = ["PASS", "REVIEW_REQUIRED", "BLOCKED", "DRAFT_ONLY"]


def gate_status_figure(rows: List[Dict[str, Any]]) -> go.Figure:
    counts = Counter(r.get("gate_status") for r in rows)
    x = [s for s in _STATUS_ORDER if counts.get(s)]
    y = [counts[s] for s in x]
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=[STATUS_COLORS.get(s, "#888") for s in x]))
    fig.update_layout(
        title="Gate outcomes across the synthetic fleet",
        margin=dict(l=30, r=20, t=40, b=30), height=280,
        paper_bgcolor="white", plot_bgcolor="white", yaxis_title="assets",
    )
    return fig


def criticality_figure(rows: List[Dict[str, Any]]) -> go.Figure:
    counts = Counter(str(r.get("criticality")) for r in rows)
    order = ["0", "1", "2", "3", "4", "N"]
    x = [c for c in order if counts.get(c)]
    y = [counts[c] for c in x]
    fig = go.Figure(go.Bar(x=x, y=y, marker_color="#0b5cab"))
    fig.update_layout(
        title="Criticality distribution (synthetic)",
        margin=dict(l=30, r=20, t=40, b=30), height=280,
        paper_bgcolor="white", plot_bgcolor="white", xaxis_title="ABC criticality", yaxis_title="assets",
    )
    return fig
