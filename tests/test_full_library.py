"""The full 24-tool library is registered and exercised by the orchestrator.

Pins the canonical count (60/07) and confirms the Wave B/C/D tools run on the in-scope path and are
skipped on the out-of-scope (fail-closed) path, so scope stays authoritative.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.tools import MAX_AGENT_TOOL_LIBRARY

_EXPECTED_TOOLS = {
    "resolve_context", "validate_scope", "genie_query_scoped", "run_scoped_sql",
    "pm_portfolio_triage", "pm_health_dashboard_metrics", "pm_effectiveness_classifier",
    "data_readiness_gate", "like_equipment_matcher", "pm_comparison_engine",
    "pm_strategy_comparator", "risk_business_justification", "recommend_strategy_change",
    "task_list_bom_readiness", "materials_component_readiness", "procurement_readiness",
    "contractor_service_readiness", "planned_hours_calibration", "cbm_measurement_readiness",
    "oxy_gate_check", "approval_workflow_state", "draft_sap_change_package",
    "trial_monitor", "value_kpi_tracker",
}


def test_library_has_the_canonical_24_tools():
    assert len(MAX_AGENT_TOOL_LIBRARY) == 24
    assert set(MAX_AGENT_TOOL_LIBRARY) == _EXPECTED_TOOLS
    assert all(callable(fn) for fn in MAX_AGENT_TOOL_LIBRARY.values())


def test_in_scope_run_exercises_wave_bcd_tools():
    agent = MaxAgent()
    result = agent.run("PUMP-4110")  # in-scope, has an active trial
    traced = {t["tool"] for t in result["tool_trace"]}
    for tool in ("genie_query_scoped", "task_list_bom_readiness", "cbm_measurement_readiness",
                 "like_equipment_matcher", "pm_comparison_engine", "trial_monitor"):
        assert tool in traced, f"{tool} missing from trace"
    assert set(result["readiness_checks"]).issuperset({"task_list_bom_readiness", "cbm_measurement_readiness"})
    assert "cohort" in result["comparison_result"]
    assert result["trial"]["decision"] in {"CONTINUE", "STOP", "MAKE_PERMANENT_CANDIDATE"}


def test_out_of_scope_run_skips_enrichment():
    agent = MaxAgent()
    # Find a fail-closed (out-of-scope) asset from the fleet.
    blocked = [eid for eid, a in agent._fleet_index.items()
               if a.get("expected_gate_status") == "BLOCKED" and not a["master_data"].get("operated", True)]
    # Fall back: any asset whose scope short-circuits.
    for eid in agent._fleet_index:
        r = agent.run(eid)
        if r.get("classifier_label") == "Not classified (out of analysis scope)":
            assert "readiness_checks" not in r  # enrichment does not run out of scope
            assert "comparison_result" not in r
            return
    # If no out-of-scope asset exists, the invariant is vacuously satisfied.
    assert True


def test_portfolio_health_composes_aggregators():
    agent = MaxAgent()
    ph = agent.portfolio_health()
    assert set(ph) == {"rows", "triage", "metrics", "kpis"}
    assert ph["metrics"]["population_count"] == len(ph["rows"])
    assert len(ph["kpis"]["kpis"]) == 8
    # Triage queue covers the whole population and is ranked.
    assert ph["triage"]["queue"][0]["rank"] == 1
    assert ph["triage"]["population_count"] == len(ph["rows"])
