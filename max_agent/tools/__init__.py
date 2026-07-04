"""MAX Agent single tool library - the canonical 24 tools.

Canonical tool names come from ``60 - MVP Scope and Design/07 - MAX Agent Single Tool Library``.
Do not rename tools or mix aliases (e.g. use ``draft_sap_change_package``, never
``sap_change_package_drafter``). Layers/build order follow ``70 - MAX Agent Build/04``.

The safety-critical tools are deterministic and unit-tested (Wave A + governance). The Wave B/C/D
tools aggregate or check readiness deterministically; none invents an Oxy value or claims savings.
"""

# Context (2)
from .context import resolve_context, validate_scope
# Data retrieval (2)
from .retrieval import genie_query_scoped, run_scoped_sql
# Portfolio health (2)
from .portfolio import pm_portfolio_triage, pm_health_dashboard_metrics
# Classification and confidence (2)
from .classification import pm_effectiveness_classifier, data_readiness_gate
# Comparison (2)
from .comparison import like_equipment_matcher, pm_comparison_engine
# Recommendation (3)
from .recommendation import pm_strategy_comparator, risk_business_justification, recommend_strategy_change
# Execution readiness (6)
from .readiness import (
    task_list_bom_readiness,
    materials_component_readiness,
    procurement_readiness,
    contractor_service_readiness,
    planned_hours_calibration,
    cbm_measurement_readiness,
)
# Governance (2)
from .governance import oxy_gate_check, approval_workflow_state
# Package and monitoring (3)
from .package import draft_sap_change_package
from .monitoring import trial_monitor, value_kpi_tracker

# Canonical name -> callable. The full 24-tool library.
MAX_AGENT_TOOL_LIBRARY = {
    # context
    "resolve_context": resolve_context,
    "validate_scope": validate_scope,
    # data retrieval
    "genie_query_scoped": genie_query_scoped,
    "run_scoped_sql": run_scoped_sql,
    # portfolio health
    "pm_portfolio_triage": pm_portfolio_triage,
    "pm_health_dashboard_metrics": pm_health_dashboard_metrics,
    # classification and confidence
    "pm_effectiveness_classifier": pm_effectiveness_classifier,
    "data_readiness_gate": data_readiness_gate,
    # comparison
    "like_equipment_matcher": like_equipment_matcher,
    "pm_comparison_engine": pm_comparison_engine,
    # recommendation
    "pm_strategy_comparator": pm_strategy_comparator,
    "risk_business_justification": risk_business_justification,
    "recommend_strategy_change": recommend_strategy_change,
    # execution readiness
    "task_list_bom_readiness": task_list_bom_readiness,
    "materials_component_readiness": materials_component_readiness,
    "procurement_readiness": procurement_readiness,
    "contractor_service_readiness": contractor_service_readiness,
    "planned_hours_calibration": planned_hours_calibration,
    "cbm_measurement_readiness": cbm_measurement_readiness,
    # governance
    "oxy_gate_check": oxy_gate_check,
    "approval_workflow_state": approval_workflow_state,
    # package and monitoring
    "draft_sap_change_package": draft_sap_change_package,
    "trial_monitor": trial_monitor,
    "value_kpi_tracker": value_kpi_tracker,
}

# The deterministic safety core (unit-tested subset), kept for callers that pin it.
MAX_AGENT_DETERMINISTIC_TOOLS = {
    k: MAX_AGENT_TOOL_LIBRARY[k]
    for k in (
        "resolve_context", "validate_scope", "run_scoped_sql", "pm_effectiveness_classifier",
        "data_readiness_gate", "pm_strategy_comparator", "risk_business_justification",
        "recommend_strategy_change", "oxy_gate_check", "approval_workflow_state", "draft_sap_change_package",
    )
}

assert len(MAX_AGENT_TOOL_LIBRARY) == 24, f"expected 24 tools, got {len(MAX_AGENT_TOOL_LIBRARY)}"

__all__ = list(MAX_AGENT_TOOL_LIBRARY) + ["MAX_AGENT_TOOL_LIBRARY", "MAX_AGENT_DETERMINISTIC_TOOLS"]
