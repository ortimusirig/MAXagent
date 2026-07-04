"""Monitoring / value tools (Wave D): value_kpi_tracker and trial_monitor.

value_kpi_tracker must stay BASELINE-ONLY: no KPI may claim realized savings or avoided hours
(labor cost is 0 in the SOAR sample). trial_monitor decides continue/stop/permanent from
evidence only and never auto-makes-permanent.
"""

from __future__ import annotations

from max_agent.tools import trial_monitor, value_kpi_tracker

_ROWS = [
    {"equipment_id": "A", "label": "Effective"},
    {"equipment_id": "B", "label": "Governance Review Required"},
    {"equipment_id": "C", "label": "Not classified (out of analysis scope)"},
]


# --- value_kpi_tracker --------------------------------------------------------

def test_kpis_are_baseline_only_no_savings_claim():
    env = value_kpi_tracker(_ROWS)
    kpis = env["data"]["kpis"]
    assert len(kpis) == 8
    assert all(k["savings_claim_allowed"] is False for k in kpis)
    assert "not claimed" in env["data"]["value_note"]


def test_avoided_hours_kpi_is_not_computable():
    env = value_kpi_tracker(_ROWS)
    avoided = next(k for k in env["data"]["kpis"] if k["kpi"] == "avoided_work_hours")
    assert avoided["basis"] == "not_computable_labor_actuals_absent"
    assert avoided["value"] is None


def test_pms_classified_excludes_out_of_scope():
    env = value_kpi_tracker(_ROWS)
    classified = next(k for k in env["data"]["kpis"] if k["kpi"] == "pms_classified")
    assert classified["value"] == 2  # A and B classified; C is out-of-scope


# --- trial_monitor ------------------------------------------------------------

def test_trial_stops_on_failure_after_pm():
    env = trial_monitor({"cycles_completed": 1, "target_cycles": 3, "failures_after_pm": 1})
    assert env["data"]["decision"] == "STOP"


def test_trial_continues_while_in_progress():
    env = trial_monitor({"cycles_completed": 2, "target_cycles": 3, "failures_after_pm": 0})
    assert env["data"]["decision"] == "CONTINUE"


def test_trial_complete_is_permanent_candidate_not_auto_permanent():
    env = trial_monitor({"cycles_completed": 3, "target_cycles": 3, "failures_after_pm": 0})
    assert env["data"]["decision"] == "MAKE_PERMANENT_CANDIDATE"
    assert "does not auto-make-permanent" in env["data"]["note"]
