"""Chat-answer rendering for the left panel.

Renders the answer as markdown (so an LLM's headings/bold/lists look clean) and shows a badge stating
whether the answer was LLM-generated or the deterministic fallback. The DECISION is always
deterministic (see the pills / Decision tab); this panel is only the narration.
"""

from __future__ import annotations

from typing import Any, Dict

from dash import dcc, html

from .theme import COLORS

# orchestration_mode -> (badge label, color)
_MODE = {
    "llm_narrated": ("LLM-generated answer", "#1a7f37"),
    "llm_orchestrated": ("LLM tool-calling answer", "#1a7f37"),
    "llm_narration_rejected": ("LLM answer rejected - deterministic shown", "#b7791f"),
    "deterministic_only": ("Deterministic answer (bind an LLM endpoint for prose)", COLORS["muted"]),
}


def render_chat(result: Dict[str, Any]) -> html.Div:
    if "error" in result:
        return html.Div(result["error"], style={"color": "#b42318"})
    summary = result.get("chat_summary", "") or ""
    label, color = _MODE.get(result.get("orchestration_mode", "deterministic_only"), _MODE["deterministic_only"])
    return html.Div([
        html.Span(label, style={
            "display": "inline-block", "padding": "2px 9px", "borderRadius": "999px",
            "background": color, "color": "white", "fontSize": "11px", "fontWeight": 700, "marginBottom": "8px",
        }),
        dcc.Markdown(summary, style={"fontSize": "13px", "lineHeight": "1.5", "color": COLORS["ink"]}),
    ], style={
        "background": "#eef4fb", "border": f"1px solid {COLORS['line']}",
        "borderRadius": "10px", "padding": "14px",
    })
