"""Theme constants and shared styles for the MAX Agent UI. Plain palette, no emoji."""

COLORS = {
    "bg": "#f4f6f9",
    "panel": "#ffffff",
    "ink": "#17242f",
    "muted": "#5b6b7a",
    "line": "#e2e8f0",
    "oxy": "#0b5cab",
    "chip": "#eef2f7",
}

# Gate status -> color.
STATUS_COLORS = {
    "PASS": "#1a7f37",
    "REVIEW_REQUIRED": "#b7791f",
    "BLOCKED": "#b42318",
    "DRAFT_ONLY": "#0b5cab",
}

# Classifier label -> color.
LABEL_COLORS = {
    "Governance Review Required": "#6b46c1",
    "Missing Evidence": "#5b6b7a",
    "Effective": "#1a7f37",
    "Needs Improvement": "#b7791f",
    "Ineffective": "#b42318",
}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

CARD = {
    "background": COLORS["panel"],
    "border": f"1px solid {COLORS['line']}",
    "borderRadius": "10px",
    "padding": "16px",
    "marginBottom": "12px",
}

H2 = {"fontSize": "15px", "fontWeight": 700, "color": COLORS["ink"], "margin": "0 0 8px 0"}
MUTED = {"color": COLORS["muted"], "fontSize": "13px"}
