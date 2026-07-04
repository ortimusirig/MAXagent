"""Portfolio-health (Wave B) and comparison (Wave B) tools.

Triage ordering must surface BLOCKED / governance-review PMs first; the health metrics must be
counts only (no realized-savings implied); comparison must never invent a value and every
standardization candidate remains a draft that clears the gate.
"""

from __future__ import annotations

from max_agent.tools import (
    like_equipment_matcher,
    pm_comparison_engine,
    pm_health_dashboard_metrics,
    pm_portfolio_triage,
)

_ROWS = [
    {"equipment_id": "A-PASS", "criticality": "2", "label": "Effective", "gate_status": "PASS",
     "gate_reason": None, "do_not_optimize": False, "provenance": "SYNTHETIC"},
    {"equipment_id": "B-BLOCK", "criticality": "4", "label": "Governance Review Required",
     "gate_status": "BLOCKED", "gate_reason": "strategy-coverage mandate", "do_not_optimize": True,
     "provenance": "SYNTHETIC"},
    {"equipment_id": "C-REVIEW", "criticality": "3", "label": "Missing Evidence",
     "gate_status": "REVIEW_REQUIRED", "gate_reason": "data readiness", "do_not_optimize": False,
     "provenance": "SYNTHETIC"},
]


# --- pm_portfolio_triage ------------------------------------------------------

def test_triage_puts_blocked_first():
    env = pm_portfolio_triage(_ROWS)
    queue = env["data"]["queue"]
    assert queue[0]["equipment_id"] == "B-BLOCK"
    assert queue[0]["rank"] == 1
    assert env["data"]["population_count"] == 3


def test_triage_empty_population():
    env = pm_portfolio_triage([])
    assert env["data"]["queue"] == []
    assert env["data"]["population_count"] == 0


# --- pm_health_dashboard_metrics ----------------------------------------------

def test_health_metrics_counts_only_no_savings():
    env = pm_health_dashboard_metrics(_ROWS)
    d = env["data"]
    assert d["population_count"] == 3
    assert d["by_gate_status"]["BLOCKED"] == 1
    assert d["blocked_count"] == 1
    assert d["do_not_optimize_count"] == 1
    assert "no realized-savings" in d["value_note"]


# --- like_equipment_matcher ---------------------------------------------------

def _asset(eid, aclass, crit):
    return {"equipment_id": eid, "asset_class": aclass, "master_data": {"criticality": {"code": crit}},
            "current_strategy": {"strategy_type": "TIME", "cycle": "M"},
            "readiness": {"maintenance_package": "ST_MON", "planned_hours": 4.0, "work_center": "MECH01"}}


def test_matcher_matches_class_and_ranks_criticality():
    target = _asset("T1", "PUMP_CENTRIFUGAL", "3")
    fleet = [target, _asset("P2", "PUMP_CENTRIFUGAL", "3"), _asset("P3", "PUMP_CENTRIFUGAL", "2"),
             _asset("C9", "COMPRESSOR", "3")]
    env = like_equipment_matcher(target, fleet)
    cohort_ids = {c["equipment_id"] for c in env["data"]["cohort"]}
    assert cohort_ids == {"P2", "P3"}  # same class only, target excluded, compressor excluded
    by_id = {c["equipment_id"]: c["match_basis"] for c in env["data"]["cohort"]}
    assert by_id["P2"] == "class+criticality"
    assert by_id["P3"] == "class"


def test_matcher_no_matches_is_low_confidence():
    target = _asset("T1", "PUMP_CENTRIFUGAL", "3")
    env = like_equipment_matcher(target, [target, _asset("C9", "COMPRESSOR", "3")])
    assert env["data"]["cohort"] == []
    assert env["confidence"] == "low"


# --- pm_comparison_engine -----------------------------------------------------

def test_comparison_flags_differing_strategy_as_candidate():
    target = _asset("T1", "PUMP_CENTRIFUGAL", "3")
    other = _asset("P2", "PUMP_CENTRIFUGAL", "3")
    other["current_strategy"] = {"strategy_type": "TIME", "cycle": "Q"}  # differs on cycle
    env = pm_comparison_engine(target, [other])
    assert "P2" in env["data"]["standardization_candidates"]
    assert "clears oxy_gate_check" in env["data"]["note"]


def test_comparison_identical_cohort_has_no_candidates():
    target = _asset("T1", "PUMP_CENTRIFUGAL", "3")
    same = _asset("P2", "PUMP_CENTRIFUGAL", "3")
    env = pm_comparison_engine(target, [same])
    assert env["data"]["standardization_candidates"] == []
