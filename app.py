"""MAX Agent - Databricks App entry point (Dash).

Runs locally on synthetic data with no Databricks connection, and on Databricks Apps once a
workspace / SQL warehouse / Genie space / LLM serving endpoint are bound (see app.yaml, DEPLOY.md).
Deterministic tools decide; the LLM only narrates; MAX never writes SAP in Wave 1.
"""

from __future__ import annotations

import os

from dash import Dash, Input, Output

from max_agent.orchestrator import MaxAgent
from max_agent.ui.artifacts import (
    render_comparison,
    render_decision,
    render_evidence,
    render_pm_health,
    render_sap_package,
    render_tool_trace,
)
from max_agent.ui.chat import render_chat
from max_agent.ui.layout import build_layout

agent = MaxAgent()
# PM Health is deterministic and static for the synthetic fleet; compute once.
# portfolio_health() composes the Wave B/D aggregators (triage + metrics + baseline KPIs).
PORTFOLIO_HEALTH = agent.portfolio_health()

app = Dash(__name__, title="MAX Agent")
server = app.server  # WSGI entry point for gunicorn / Databricks Apps
app.layout = build_layout(agent)


@app.callback(
    Output("user-question", "children"),
    Output("chat-output", "children"),
    Output("tab-decision", "children"),
    Output("tab-evidence", "children"),
    Output("tab-pmhealth", "children"),
    Output("tab-comparison", "children"),
    Output("tab-sap", "children"),
    Output("tab-trace", "children"),
    Input("asset-dropdown", "value"),
)
def on_select(equipment_id):
    result = agent.run(equipment_id)
    question = '"' + str(result.get("user_question", "")) + '"'
    return (
        question,
        render_chat(result),
        render_decision(result),
        render_evidence(result),
        render_pm_health(PORTFOLIO_HEALTH),
        render_comparison(result),
        render_sap_package(result),
        render_tool_trace(result),
    )


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
    app.run(host="0.0.0.0", port=port, debug=False)
