"""Chat-answer rendering for the left panel."""

from __future__ import annotations

from typing import Any, Dict, List

from dash import html

from .theme import COLORS

_HEADERS = {"Overview", "Key Findings", "Recommendation"}


def render_chat(result: Dict[str, Any]) -> html.Div:
    if "error" in result:
        return html.Div(result["error"], style={"color": "#b42318"})
    summary = result.get("chat_summary", "")
    blocks: List[Any] = []
    for line in summary.splitlines():
        s = line.strip()
        if not s:
            blocks.append(html.Div(style={"height": "6px"}))
        elif s in _HEADERS:
            blocks.append(html.Div(s, style={"fontWeight": 700, "color": COLORS["ink"], "marginTop": "8px", "fontSize": "13px"}))
        elif s.startswith("- "):
            blocks.append(html.Div(s[2:], style={"fontSize": "13px", "color": COLORS["muted"], "margin": "2px 0 2px 10px"}))
        else:
            blocks.append(html.Div(s, style={"fontSize": "13px", "color": COLORS["muted"]}))
    return html.Div(
        blocks,
        style={
            "background": "#eef4fb", "border": f"1px solid {COLORS['line']}",
            "borderRadius": "10px", "padding": "14px", "lineHeight": "1.45",
        },
    )
