"""MAX Agent single tool library - the canonical 24 tools + 6 evidence extensions (30).

Canonical tool names come from ``60 - MVP Scope and Design/07 - MAX Agent Single Tool Library``.
Do not rename tools or mix aliases (e.g. use ``draft_sap_change_package``, never
``sap_change_package_drafter``). Layers/build order follow ``70 - MAX Agent Build/04``.

The safety-critical tools are deterministic and unit-tested (Wave A + governance). The Wave B/C/D
tools aggregate or check readiness deterministically; none invents an Oxy value or claims savings.

Tools 25-27 (reliability_metrics, weibull_reliability, failure_mode_summary) are a Wave-B reliability-
EVIDENCE extension (60/07 extension): they compute reliability facts + a math-defensible interpretation
that feeds the narration / recommendation rationale. Tool 28 (pm_bom_completeness) is a parts / BOM-
completeness EVIDENCE extension: it compares this PM's linked components to like equipment and flags
missing ones, which feeds the ADD_COMPONENT recommendation. Tools 29-30 (reliability_drift_monitor,
sap_cost_distribution) are a SAP-transactional anomaly / drift EVIDENCE extension: they redesign the
reference PdM agent's sensor-based anomaly detection onto Oxy's transactional SAP (failure timing,
work-order mix, cost), flagging drift/outliers + a candidate recommendation TYPE. All six are EVIDENCE
ONLY - they never change the classifier label or the gate, and every judgment threshold stays
BU_DEFINED until Oxy confirms it.
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
# Reliability evidence (3) - Wave-B extension (tools 25-27), evidence-only
from .reliability import reliability_metrics, weibull_reliability, failure_mode_summary
# Parts / BOM-completeness evidence (1) - tool 28, evidence-only; feeds ADD_COMPONENT
from .bom import pm_bom_completeness
# SAP-transactional anomaly / drift evidence (2) - tools 29-30, evidence-only; flag candidate rec TYPE
from .anomaly import reactive_share, reliability_drift_monitor, sap_cost_distribution

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
    # reliability evidence (Wave-B extension, tools 25-27; evidence-only)
    "reliability_metrics": reliability_metrics,
    "weibull_reliability": weibull_reliability,
    "failure_mode_summary": failure_mode_summary,
    # parts / BOM-completeness evidence (tool 28; evidence-only, feeds ADD_COMPONENT)
    "pm_bom_completeness": pm_bom_completeness,
    # SAP-transactional anomaly / drift evidence (tools 29-30; evidence-only, flag candidate rec TYPE)
    "reliability_drift_monitor": reliability_drift_monitor,
    "sap_cost_distribution": sap_cost_distribution,
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

assert len(MAX_AGENT_TOOL_LIBRARY) == 30, f"expected 30 tools (24 canonical + 3 reliability + 1 BOM + 2 anomaly), got {len(MAX_AGENT_TOOL_LIBRARY)}"

__all__ = list(MAX_AGENT_TOOL_LIBRARY) + ["MAX_AGENT_TOOL_LIBRARY", "MAX_AGENT_DETERMINISTIC_TOOLS",
                                          "reactive_share"]
